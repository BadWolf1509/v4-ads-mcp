"""Caracterização do bookkeeping dos 6 executores Google (P6, T6.1).

Rede da refatoração do `finally` (cota + audit) para `encerrar_execucao`: estes
testes descrevem o comportamento de ANTES, e têm de continuar verdes depois,
sem edição. Por isso mexem só no que fica de pé dos dois lados — os nomes que
o executor importa e que o desenho mantém nele (`ensure_account_access`,
`reservar_cota`, `build_client_for_manager`, `time`, `get_request_id`) e os
pontos de I/O de fora (`reserva.record_actual`, `audit_log.record`,
`connection.get_pool`). Nada aqui fixa ONDE o reconcile e o audit moram.

Matriz executor x cenário:

- (a) sucesso: ordem `gate -> reserva -> client -> sdk -> reconcile -> audit`,
  retorno, `actual_ops` do reconcile e os kwargs EFETIVOS do `audit_log.record`
  (normalizados pela assinatura, com os defaults aplicados: passar
  `platform="google"` explícito ou omiti-lo dá a mesma linha);
- (b) erro do SDK: o que sobe (ou volta, no upload de conversões), o
  `actual_ops` e o audit de erro;
- (c) `QuotaExhausted` na reserva: nenhum reconcile, audit gravado e a exceção
  intacta;
- (d) `audit_log.record` levantando: retorno de (a) e exceção de (b) iguais, e
  o log ERROR com o nome do evento e o contexto de hoje;
- (e) `record_actual` levantando dentro do reconcile: o audit sai mesmo assim,
  e o log ERROR do reconcile carrega o nome e o contexto de hoje;
- (f) só `run_report`: `audit_this_call=False` não pega conexão para audit.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from src.db.repositories import audit_log
from src.google_ads import conversions, customer_match, keyword_planning, mutations, reports
from src.google_ads.errors import GoogleAdsFriendlyError
from src.google_ads.partial_failure import LeituraDeFalhas
from src.governance import bookkeeping
from src.governance.rate_limit import CHAVE_COTA_PROJETO, QuotaExhausted
from src.governance.reserva import Reserva

MANAGER = UUID("11111111-1111-1111-1111-111111111111")
SESSION = UUID("22222222-2222-2222-2222-222222222222")
CUSTOMER = "1234567890"
DIA = date(2026, 11, 15)
DURACAO_MS = 250  # o relógio falso dá 10.0 na primeira leitura e 10.25 depois

_ASSINATURA_DO_RECORD = inspect.signature(audit_log.record)
_MODULOS = (reports, keyword_planning, customer_match, conversions, mutations)


class _FalhaDoSdkError(Exception):
    pass


class _FalhaDeIoError(Exception):
    """Stand-in de conexão asyncpg derrubada (F76)."""


@dataclass
class Gravador:
    """Anota a ordem dos eventos e guarda os kwargs de cada ponto falso."""

    eventos: list[str] = field(default_factory=list)
    audits: list[dict[str, Any]] = field(default_factory=list)
    reconciles: list[dict[str, Any]] = field(default_factory=list)
    reservas: list[int] = field(default_factory=list)
    acquires: int = 0
    client: Any = None
    falha_reserva: Exception | None = None
    falha_sdk: Exception | None = None
    falha_audit: Exception | None = None
    falha_record_actual: Exception | None = None
    log_de_falha: MagicMock = field(default_factory=MagicMock)

    def evento(self, nome: str) -> None:
        self.eventos.append(nome)

    def sdk(self) -> None:
        """Chamado pelo client falso em cada RPC; levanta `falha_sdk` se houver."""
        self.evento("sdk")
        if self.falha_sdk is not None:
            raise self.falha_sdk

    @property
    def actual_ops(self) -> list[int]:
        """`actual_ops` de cada `record_actual` (um por chave de cota)."""
        return [r["actual_ops"] for r in self.reconciles]

    def eventos_de_falha(self) -> list[tuple[str, dict[str, Any]]]:
        return [(c.args[0], c.kwargs) for c in self.log_de_falha.exception.call_args_list]


class _Cm:
    def __init__(self, valor: Any = None) -> None:
        self._valor = valor

    async def __aenter__(self) -> Any:
        return self._valor

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _Conn:
    def transaction(self) -> _Cm:
        return _Cm()


class _Pool:
    def __init__(self, g: Gravador) -> None:
        self._g = g

    def acquire(self) -> _Cm:
        self._g.acquires += 1
        return _Cm(_Conn())


@pytest.fixture
def gravador(monkeypatch: pytest.MonkeyPatch) -> Gravador:
    g = Gravador()
    pool = _Pool(g)

    async def run_with_reconnect(op: Callable[[Any], Awaitable[Any]]) -> Any:
        return await op(None)

    async def gate(_conn: Any, **_kw: Any) -> None:
        g.evento("gate")

    async def reservar(_pool: Any, *, manager_id: UUID, estimated_ops: int) -> Reserva:
        g.evento("reserva")
        g.reservas.append(estimated_ops)
        if g.falha_reserva is not None:
            raise g.falha_reserva
        return Reserva(dia_projeto=DIA, dia_gestor=DIA, estimated_ops=estimated_ops)

    async def build(*, manager_id: UUID) -> Any:
        g.evento("client")
        return g.client

    async def record_actual(
        _conn: Any, chave: str, *, dia: date, actual_ops: int, estimated_ops: int
    ) -> None:
        g.evento("reconcile")
        g.reconciles.append(
            {"chave": chave, "dia": dia, "actual_ops": actual_ops, "estimated_ops": estimated_ops}
        )
        if g.falha_record_actual is not None:
            raise g.falha_record_actual

    async def record(conn: Any, **kw: Any) -> int:
        g.evento("audit")
        ligado = _ASSINATURA_DO_RECORD.bind(conn, **kw)
        ligado.apply_defaults()
        efetivos = dict(ligado.arguments)
        efetivos.pop("conn")
        g.audits.append(efetivos)
        if g.falha_audit is not None:
            raise g.falha_audit
        return 1

    leituras = {"n": 0}

    def monotonic() -> float:
        leituras["n"] += 1
        return 10.0 if leituras["n"] == 1 else 10.25

    ids = {"n": 0}

    def get_request_id() -> str:
        ids["n"] += 1
        return f"req-{ids['n']}"

    monkeypatch.setattr("src.db.connection.run_with_reconnect", run_with_reconnect)
    monkeypatch.setattr("src.db.connection.get_pool", lambda: pool)
    monkeypatch.setattr("src.governance.reserva.record_actual", record_actual)
    monkeypatch.setattr(audit_log, "record", record)
    monkeypatch.setattr(bookkeeping, "log", g.log_de_falha)
    for mod in _MODULOS:
        monkeypatch.setattr(mod, "ensure_account_access", gate)
        monkeypatch.setattr(mod, "reservar_cota", reservar)
        monkeypatch.setattr(mod, "build_client_for_manager", build)
        monkeypatch.setattr(mod, "time", SimpleNamespace(monotonic=monotonic))
        if hasattr(mod, "get_request_id"):
            monkeypatch.setattr(mod, "get_request_id", get_request_id)
            monkeypatch.setattr(mod, "reset_request_id", lambda: None)
    return g


# --------------------------------------------------------------------------
# Um `Caso` por executor: como montar o client falso, como chamar, e o que se
# espera em cada cenário. Os valores esperados são LITERAIS, medidos no código
# de antes da refatoração (T6.1).
# --------------------------------------------------------------------------


def _base_audit(**campos: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "manager_id": MANAGER,
        "session_id": SESSION,
        "customer_id": CUSTOMER,
        "target_count": None,
        "params_summary": None,
        "provider_request_id": None,
        "status": "success",
        "error_message": None,
        "duration_ms": DURACAO_MS,
        "platform": "google",
        "dry_run": None,
        "had_effect": None,
    }
    base.update(campos)
    return base


@dataclass
class Caso:
    nome: str
    preparar: Callable[[Gravador, pytest.MonkeyPatch], None]
    rodar: Callable[..., Awaitable[Any]]
    eventos_sucesso: list[str]
    retorno_sucesso: Any
    audit_sucesso: dict[str, Any]
    actual_ops_sucesso: int
    actual_ops_erro: int
    audit_erro: Callable[[BaseException | None, Any], dict[str, Any]]
    # True: o erro do SDK volta como envelope (só o upload de conversões).
    erro_vira_retorno: bool
    evento_cota: str
    evento_audit: str
    operation: str
    reserva_estimada: int


# ---- run_report ----------------------------------------------------------


def _preparar_report(g: Gravador, _mp: pytest.MonkeyPatch) -> None:
    client = MagicMock()

    def search_stream(request: Any) -> list[Any]:
        g.sdk()
        return [SimpleNamespace(request_id="req-stream", results=["r1", "r2"])]

    client.get_service.return_value.search_stream.side_effect = search_stream
    g.client = client


async def _rodar_report(audit_this_call: bool = True) -> Any:
    return await reports.run_report(
        manager_id=MANAGER,
        session_id=SESSION,
        customer_id=CUSTOMER,
        query="SELECT campaign.id FROM campaign",
        row_formatter=lambda row: {"v": row},
        operation_name="get_campaign_performance",
        estimated_ops=1,
        audit_this_call=audit_this_call,
        params_summary={"date_range": "LAST_7_DAYS"},
    )


CASO_REPORT = Caso(
    nome="run_report",
    preparar=_preparar_report,
    rodar=_rodar_report,
    eventos_sucesso=["gate", "reserva", "client", "sdk", "reconcile", "reconcile", "audit"],
    retorno_sucesso=[{"v": "r1"}, {"v": "r2"}],
    audit_sucesso=_base_audit(
        action_type="read",
        operation="get_campaign_performance",
        target_count=2,
        params_summary={"date_range": "LAST_7_DAYS"},
        provider_request_id="req-stream",
    ),
    actual_ops_sucesso=1,
    actual_ops_erro=0,
    audit_erro=lambda exc, _r: _base_audit(
        action_type="read",
        operation="get_campaign_performance",
        params_summary={"date_range": "LAST_7_DAYS"},
        status="error",
        error_message=str(exc),
    ),
    erro_vira_retorno=False,
    evento_cota="report_quota_reconcile_failed",
    evento_audit="report_audit_write_failed",
    operation="get_campaign_performance",
    reserva_estimada=1,
)


# ---- run_keyword_planning ------------------------------------------------


def _preparar_keyword_planning(g: Gravador, _mp: pytest.MonkeyPatch) -> None:
    g.client = MagicMock()


async def _rodar_keyword_planning() -> Any:
    g_atual: Gravador = _GRAVADOR_ATUAL["g"]

    def chamadas(_client: Any) -> list[str]:
        g_atual.sdk()
        return ["ideia1", "ideia2", "ideia3"]

    return await keyword_planning.run_keyword_planning(
        manager_id=MANAGER,
        session_id=SESSION,
        customer_id=CUSTOMER,
        operation_name="generate_keyword_ideas",
        estimated_ops=7,
        params_summary={"seed_count": 2},
        chamadas=chamadas,
        resumo_do_resultado=lambda r: {"ideias": len(r)},
    )


CASO_KEYWORD_PLANNING = Caso(
    nome="run_keyword_planning",
    preparar=_preparar_keyword_planning,
    rodar=_rodar_keyword_planning,
    eventos_sucesso=["gate", "reserva", "client", "sdk", "reconcile", "reconcile", "audit"],
    retorno_sucesso=["ideia1", "ideia2", "ideia3"],
    audit_sucesso=_base_audit(
        action_type="read",
        operation="generate_keyword_ideas",
        target_count=3,
        params_summary={"seed_count": 2, "ideias": 3},
        provider_request_id="req-1",
    ),
    actual_ops_sucesso=7,
    actual_ops_erro=0,
    # error_message e o texto do ORIGINAL (nao do amigavel), e o request-id e
    # lido no `finally` do closure, entao existe mesmo no erro.
    audit_erro=lambda exc, _r: _base_audit(
        action_type="read",
        operation="generate_keyword_ideas",
        params_summary={"seed_count": 2},
        provider_request_id="req-1" if not isinstance(exc, QuotaExhausted) else None,
        status="error",
        error_message=str(exc.__cause__ if isinstance(exc, GoogleAdsFriendlyError) else exc),
    ),
    erro_vira_retorno=False,
    evento_cota="keyword_planning_quota_reconcile_failed",
    evento_audit="keyword_planning_audit_write_failed",
    operation="generate_keyword_ideas",
    reserva_estimada=7,
)


# ---- run_offline_user_data_job -------------------------------------------

_JOB = "customers/1234567890/offlineUserDataJobs/77"


def _preparar_customer_match(g: Gravador, mp: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    service = client.get_service.return_value

    def create(**_kw: Any) -> Any:
        g.evento("sdk")
        return SimpleNamespace(resource_name=_JOB)

    def add(**_kw: Any) -> Any:
        g.evento("sdk")
        return MagicMock()

    def run(**_kw: Any) -> None:
        # O erro do SDK cai no passo 3: a PII ja esta anexada, e o resumo do
        # audit tem de dizer onde parou (R1-I3/I4).
        g.sdk()

    service.create_offline_user_data_job.side_effect = create
    service.add_offline_user_data_job_operations.side_effect = add
    service.run_offline_user_data_job.side_effect = run
    mp.setattr(customer_match, "_build_user_data_operations", lambda *_a: [])
    mp.setattr(
        customer_match,
        "erros_por_indice",
        lambda *_a, **_k: LeituraDeFalhas(erros={}, medido=True),
    )
    g.client = client


async def _rodar_customer_match() -> Any:
    return await customer_match.run_offline_user_data_job(
        manager_id=MANAGER,
        session_id=SESSION,
        customer_id=CUSTOMER,
        user_list_id="555",
        operation_type="add",
        hashed_members=[{"hashed_email": "a"}, {"hashed_email": "b"}],
    )


def _audit_erro_customer_match(exc: BaseException | None, _r: Any) -> dict[str, Any]:
    if isinstance(exc, QuotaExhausted):
        resumo: dict[str, Any] = {
            "etapa": "create_job",
            "job_resource_name": None,
            "pii_anexada": False,
            "members_submitted": 0,
            "members_failed": 0,
        }
        provider = None
        mensagem = str(exc)
    else:
        resumo = {
            "etapa": "run_job",
            "job_resource_name": _JOB,
            "pii_anexada": True,
            "members_submitted": 2,
            "members_failed": 0,
        }
        provider = "req-2"
        assert exc is not None
        mensagem = str(exc.__cause__)
    return _base_audit(
        action_type="mutate",
        operation="upload_customer_match_list",
        target_count=2,
        params_summary={"user_list_id": "555", "operation": "add", "member_count": 2, **resumo},
        provider_request_id=provider,
        status="error",
        error_message=mensagem,
    )


CASO_CUSTOMER_MATCH = Caso(
    nome="run_offline_user_data_job",
    preparar=_preparar_customer_match,
    rodar=_rodar_customer_match,
    eventos_sucesso=[
        "gate",
        "reserva",
        "client",
        "sdk",
        "sdk",
        "sdk",
        "reconcile",
        "reconcile",
        "audit",
    ],
    retorno_sucesso={
        "job_resource_name": _JOB,
        "provider_request_id_create_job": "req-1",
        "provider_request_id_add_ops": "req-2",
        "provider_request_id_run_job": "req-3",
        "members_submitted": 2,
        "members_failed": 0,
        "failures": [],
        "recusas_medidas": True,
    },
    audit_sucesso=_base_audit(
        action_type="mutate",
        operation="upload_customer_match_list",
        target_count=2,
        params_summary={
            "user_list_id": "555",
            "operation": "add",
            "member_count": 2,
            "etapa": "concluido",
            "job_resource_name": _JOB,
            "pii_anexada": True,
            "members_submitted": 2,
            "members_failed": 0,
        },
        provider_request_id="req-3",
    ),
    actual_ops_sucesso=3,
    actual_ops_erro=0,
    audit_erro=_audit_erro_customer_match,
    erro_vira_retorno=False,
    evento_cota="customer_match_quota_reconcile_failed",
    evento_audit="customer_match_audit_write_failed",
    operation="upload_customer_match_list",
    reserva_estimada=3,
)


# ---- run_conversion_upload -----------------------------------------------

_PAYLOAD_CONVERSOES = {
    "__time_zone__": "America/Sao_Paulo",
    "conversion_action_id": "999",
    "conversions": [
        {"gclid": "g1", "conversion_date_time": "2026-11-10 10:00:00", "conversion_value_brl": 10},
        {"gclid": "g2", "conversion_date_time": "2026-11-10 11:00:00", "conversion_value_brl": 20},
    ],
}


def _preparar_conversions(g: Gravador, mp: pytest.MonkeyPatch) -> None:
    client = MagicMock()

    def upload(**_kw: Any) -> Any:
        g.sdk()
        return MagicMock()

    client.get_service.return_value.upload_click_conversions.side_effect = upload
    mp.setattr(conversions, "_parse_upload_response", lambda *_a: (2, 0, [], True))
    g.client = client


async def _rodar_conversions() -> Any:
    return await conversions.run_conversion_upload(
        manager_id=MANAGER,
        session_id=SESSION,
        customer_id=CUSTOMER,
        operation_type="import_offline_conversions",
        payload=_PAYLOAD_CONVERSOES,
        target_count=2,
        params_summary={"conversion_count": 2},
    )


CASO_CONVERSIONS = Caso(
    nome="run_conversion_upload",
    preparar=_preparar_conversions,
    rodar=_rodar_conversions,
    eventos_sucesso=["gate", "reserva", "client", "sdk", "reconcile", "reconcile", "audit"],
    retorno_sucesso={
        "status": "applied",
        "operation": "import_offline_conversions",
        "customer_id": CUSTOMER,
        "applied_count": 2,
        "failed_count": 0,
        "failures": [],
        "provider_request_id": "req-1",
        "motivos_medidos": True,
    },
    audit_sucesso=_base_audit(
        action_type="mutate",
        operation="import_offline_conversions",
        target_count=2,
        params_summary={"conversion_count": 2, "applied_count": 2, "failed_count": 0},
        provider_request_id="req-1",
        had_effect=True,
    ),
    actual_ops_sucesso=2,
    actual_ops_erro=0,
    # O audit de erro guarda o texto do ORIGINAL; o envelope, o do amigavel.
    audit_erro=lambda exc, _r: _base_audit(
        action_type="mutate",
        operation="import_offline_conversions",
        target_count=2,
        params_summary={"conversion_count": 2},
        status="error",
        error_message="boom do sdk" if not isinstance(exc, QuotaExhausted) else str(exc),
    ),
    erro_vira_retorno=True,
    evento_cota="conversion_upload_quota_reconcile_failed",
    evento_audit="conversion_upload_audit_write_failed",
    operation="import_offline_conversions",
    reserva_estimada=2,
)


# ---- run_mutation --------------------------------------------------------

_CAMPANHA = "customers/1234567890/campaigns/1"


def _preparar_mutation(g: Gravador, mp: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    raw = MagicMock()
    raw.WhichOneof.return_value = "campaign_result"
    raw.campaign_result.resource_name = _CAMPANHA
    resposta = SimpleNamespace(mutate_operation_responses=[SimpleNamespace(_pb=raw)])

    def mutate(**_kw: Any) -> Any:
        g.sdk()
        return resposta

    client.get_service.return_value.mutate.side_effect = mutate
    mp.setattr(mutations, "get_builder", lambda _op: lambda _c, _cid, _p: [MagicMock()])
    g.client = client


async def _rodar_mutation() -> Any:
    return await mutations.run_mutation(
        manager_id=MANAGER,
        session_id=SESSION,
        customer_id=CUSTOMER,
        operation_type="update_campaign_status",
        payload={"status": "PAUSED", "campaign_id": "1"},
        target_count=1,
    )


CASO_MUTATION = Caso(
    nome="run_mutation",
    preparar=_preparar_mutation,
    rodar=_rodar_mutation,
    eventos_sucesso=["gate", "reserva", "client", "sdk", "reconcile", "reconcile", "audit"],
    retorno_sucesso={
        "provider_request_id": "req-1",
        "applied_count": 1,
        "changed_count": 1,
        "partial_failures": [],
        "resource_names": [_CAMPANHA],
        "motivos_medidos": None,
    },
    audit_sucesso=_base_audit(
        action_type="mutate",
        operation="update_campaign_status",
        target_count=1,
        params_summary={
            "keys": ["campaign_id", "status"],
            "resultado": {"tentadas": 1, "aplicadas": 1, "mudaram": 1},
        },
        provider_request_id="req-1",
        had_effect=True,
    ),
    actual_ops_sucesso=1,
    # Mutacao reconcilia o TENTADO mesmo no erro (target_count), nao zero.
    actual_ops_erro=1,
    audit_erro=lambda exc, _r: _base_audit(
        action_type="mutate",
        operation="update_campaign_status",
        target_count=1,
        params_summary={"keys": ["campaign_id", "status"]},
        status="error",
        error_message=str(exc),
    ),
    erro_vira_retorno=False,
    evento_cota="mutation_quota_reconcile_failed",
    evento_audit="mutation_audit_write_failed",
    operation="update_campaign_status",
    reserva_estimada=1,
)


# ---- run_recommendation_action -------------------------------------------


def _preparar_recommendation(g: Gravador, mp: pytest.MonkeyPatch) -> None:
    def aplicar(_client: Any, _cid: str, _payload: Any) -> None:
        g.sdk()

    mp.setattr("src.google_ads.mutates.recommendations.execute_apply_recommendation", aplicar)
    g.client = MagicMock()


async def _rodar_recommendation() -> Any:
    return await mutations.run_recommendation_action(
        manager_id=MANAGER,
        session_id=SESSION,
        customer_id=CUSTOMER,
        operation_type="apply_recommendation",
        payload={"recommendation_resource_name": "customers/1234567890/recommendations/9"},
    )


CASO_RECOMMENDATION = Caso(
    nome="run_recommendation_action",
    preparar=_preparar_recommendation,
    rodar=_rodar_recommendation,
    eventos_sucesso=["gate", "reserva", "client", "sdk", "reconcile", "reconcile", "audit"],
    retorno_sucesso={"provider_request_id": "req-1", "applied_count": 1},
    audit_sucesso=_base_audit(
        action_type="mutate",
        operation="apply_recommendation",
        target_count=1,
        params_summary={"keys": ["recommendation_resource_name"]},
        provider_request_id="req-1",
    ),
    actual_ops_sucesso=1,
    actual_ops_erro=1,
    audit_erro=lambda exc, _r: _base_audit(
        action_type="mutate",
        operation="apply_recommendation",
        target_count=1,
        params_summary={"keys": ["recommendation_resource_name"]},
        status="error",
        error_message=str(exc),
    ),
    erro_vira_retorno=False,
    evento_cota="recommendation_quota_reconcile_failed",
    evento_audit="recommendation_audit_write_failed",
    operation="apply_recommendation",
    reserva_estimada=1,
)


CASOS = [
    CASO_REPORT,
    CASO_KEYWORD_PLANNING,
    CASO_CUSTOMER_MATCH,
    CASO_CONVERSIONS,
    CASO_MUTATION,
    CASO_RECOMMENDATION,
]

# O closure `chamadas` do run_keyword_planning e escrito pela tool, entao ele
# precisa do gravador do teste corrente.
_GRAVADOR_ATUAL: dict[str, Gravador] = {}


@pytest.fixture(params=CASOS, ids=[c.nome for c in CASOS])
def caso(
    request: pytest.FixtureRequest, gravador: Gravador, monkeypatch: pytest.MonkeyPatch
) -> Caso:
    c: Caso = request.param
    c.preparar(gravador, monkeypatch)
    _GRAVADOR_ATUAL["g"] = gravador
    return c


async def _executar(c: Caso) -> tuple[Any, BaseException | None]:
    try:
        return await c.rodar(), None
    except Exception as exc:
        return None, exc


def test_matriz_cobre_os_seis_executores() -> None:
    assert sorted(c.nome for c in CASOS) == sorted(
        [
            "run_report",
            "run_keyword_planning",
            "run_offline_user_data_job",
            "run_conversion_upload",
            "run_mutation",
            "run_recommendation_action",
        ]
    )


# ---- (a) sucesso -----------------------------------------------------------


@pytest.mark.asyncio
async def test_a_sucesso_ordem_retorno_reconcile_e_audit(caso: Caso, gravador: Gravador) -> None:
    retorno, exc = await _executar(caso)

    assert exc is None
    assert retorno == caso.retorno_sucesso
    assert gravador.eventos == caso.eventos_sucesso
    assert gravador.reservas == [caso.reserva_estimada]
    assert gravador.reconciles == [
        {
            "chave": CHAVE_COTA_PROJETO,
            "dia": DIA,
            "actual_ops": caso.actual_ops_sucesso,
            "estimated_ops": caso.reserva_estimada,
        },
        {
            "chave": f"mgr:{MANAGER}",
            "dia": DIA,
            "actual_ops": caso.actual_ops_sucesso,
            "estimated_ops": caso.reserva_estimada,
        },
    ]
    assert gravador.audits == [caso.audit_sucesso]
    # Uma conexao para o reconcile e uma para o audit (gate e reserva sao falsos).
    assert gravador.acquires == 2
    assert gravador.eventos_de_falha() == []


# ---- (b) erro do SDK -------------------------------------------------------


@pytest.mark.asyncio
async def test_b_erro_do_sdk(caso: Caso, gravador: Gravador) -> None:
    gravador.falha_sdk = _FalhaDoSdkError("boom do sdk")

    retorno, exc = await _executar(caso)

    if caso.erro_vira_retorno:
        assert exc is None
        assert retorno == {
            "status": "error",
            "operation": caso.operation,
            "customer_id": CUSTOMER,
            "error_message": retorno["error_message"],
            "provider_request_id": "",
        }
        assert retorno["error_message"].startswith("Erro inesperado")
    else:
        assert type(exc) is GoogleAdsFriendlyError
        assert isinstance(exc.__cause__, _FalhaDoSdkError)
    assert gravador.actual_ops == [caso.actual_ops_erro, caso.actual_ops_erro]
    assert gravador.eventos[-1] == "audit"
    assert gravador.audits == [caso.audit_erro(exc, retorno)]


@pytest.mark.asyncio
async def test_b_customer_match_erro_depois_da_pii_avisa_no_texto(
    gravador: Gravador, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O texto do erro (montado DEPOIS do bookkeeping) segue dizendo que a PII subiu."""
    _preparar_customer_match(gravador, monkeypatch)
    gravador.falha_sdk = _FalhaDoSdkError("boom do sdk")
    _, exc = await _executar(CASO_CUSTOMER_MATCH)
    assert type(exc) is GoogleAdsFriendlyError
    assert "NAO repita o upload" in str(exc)
    assert "2 membro(s) JA foram enviados" in str(exc)
    assert "'run_job'" in str(exc)


# ---- (c) QuotaExhausted na reserva -----------------------------------------


@pytest.mark.asyncio
async def test_c_quota_exhausted_na_reserva(caso: Caso, gravador: Gravador) -> None:
    recusa = QuotaExhausted("cota do gestor esgotada: 100/100, reset 00:00 UTC")
    gravador.falha_reserva = recusa

    retorno, exc = await _executar(caso)

    if caso.erro_vira_retorno:
        assert exc is None
        assert retorno == {
            "status": "error",
            "operation": caso.operation,
            "customer_id": CUSTOMER,
            "error_message": str(recusa),
            "provider_request_id": "",
        }
    else:
        assert exc is recusa
    assert "client" not in gravador.eventos
    assert gravador.reconciles == []
    assert gravador.eventos == ["gate", "reserva", "audit"]
    assert gravador.audits == [caso.audit_erro(recusa, retorno)]
    assert gravador.acquires == 1


# ---- (d) audit_log.record levantando ---------------------------------------


@pytest.mark.asyncio
async def test_d_audit_que_falha_nao_muda_o_retorno(caso: Caso, gravador: Gravador) -> None:
    gravador.falha_audit = _FalhaDeIoError("conexao morta")

    retorno, exc = await _executar(caso)

    assert exc is None
    assert retorno == caso.retorno_sucesso
    assert gravador.audits == [caso.audit_sucesso]
    assert gravador.eventos_de_falha() == [
        (
            caso.evento_audit,
            {"operation": caso.operation, "customer_id": CUSTOMER, "status": "success"},
        )
    ]


@pytest.mark.asyncio
async def test_d_audit_que_falha_nao_muda_o_erro(caso: Caso, gravador: Gravador) -> None:
    gravador.falha_audit = _FalhaDeIoError("conexao morta")
    gravador.falha_sdk = _FalhaDoSdkError("boom do sdk")

    retorno, exc = await _executar(caso)

    if caso.erro_vira_retorno:
        assert exc is None
        assert retorno["status"] == "error"
        assert retorno["error_message"].startswith("Erro inesperado")
    else:
        assert type(exc) is GoogleAdsFriendlyError
        assert isinstance(exc.__cause__, _FalhaDoSdkError)
    assert gravador.audits == [caso.audit_erro(exc, retorno)]
    assert gravador.eventos_de_falha() == [
        (
            caso.evento_audit,
            {"operation": caso.operation, "customer_id": CUSTOMER, "status": "error"},
        )
    ]


# ---- (e) record_actual levantando dentro do reconcile ----------------------


@pytest.mark.asyncio
async def test_e_reconcile_que_falha_nao_pula_o_audit(caso: Caso, gravador: Gravador) -> None:
    gravador.falha_record_actual = _FalhaDeIoError("conexao morta")

    retorno, exc = await _executar(caso)

    assert exc is None
    assert retorno == caso.retorno_sucesso
    # O primeiro record_actual levanta e a transacao do reconcile para ali.
    assert gravador.eventos[-2:] == ["reconcile", "audit"]
    assert gravador.audits == [caso.audit_sucesso]
    assert gravador.eventos_de_falha() == [
        (caso.evento_cota, {"operation": caso.operation, "customer_id": CUSTOMER})
    ]


# ---- (f) run_report sem opt-in de audit ------------------------------------


@pytest.mark.asyncio
async def test_f_run_report_sem_opt_in_nao_pega_conexao_para_audit(
    gravador: Gravador, monkeypatch: pytest.MonkeyPatch
) -> None:
    _preparar_report(gravador, monkeypatch)

    retorno = await _rodar_report(audit_this_call=False)

    assert retorno == [{"v": "r1"}, {"v": "r2"}]
    assert "audit" not in gravador.eventos
    assert gravador.audits == []
    # So a conexao do reconcile.
    assert gravador.acquires == 1


@pytest.mark.asyncio
async def test_f_run_report_sem_opt_in_com_quota_esgotada_nao_audita(
    gravador: Gravador, monkeypatch: pytest.MonkeyPatch
) -> None:
    _preparar_report(gravador, monkeypatch)
    recusa = QuotaExhausted("cota do projeto esgotada")
    gravador.falha_reserva = recusa

    with pytest.raises(QuotaExhausted) as info:
        await _rodar_report(audit_this_call=False)

    assert info.value is recusa
    assert gravador.eventos == ["gate", "reserva"]
    assert gravador.acquires == 0
