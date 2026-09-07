"""R1-I1..I4: o que se reporta ao gestor tem que ser o que ACONTECEU.

Quatro achados da varredura do PR3 sao a MESMA familia, em duas camadas:

- **Resposta** — `apply_change` no caminho default descartava `partial_failures`
  (R1-I1) e `run_offline_user_data_job` reportava o lote inteiro como submetido
  mesmo quando o Google recusou parte (R1-I3). Nos dois, o gestor le "aplicado"
  sem saber o que ficou de fora.
- **Trilha** — `run_mutation` gravava no audit o TENTADO (`target_count`) e
  `status="success"` mesmo apos aplicacao parcial (R1-I2), e o Customer Match
  gravava `provider_request_id=""` no audit de erro (R1-I4), contradizendo o
  comentario ao lado que prometia "o ultimo request-id bem-sucedido, util pra
  saber em qual das 3 etapas parou". A trilha e quem responde "por que essa
  conta mudou"; sem o resultado ela responde "o que foi pedido".

Cada teste aqui foi escrito para falhar contra o codigo pre-fix.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current
from tests.unit.test_mutations_partial_failure import (
    _client_with_partial_failure,
    _pool_with_transactable_conn,
)
from tests.unit.test_run_offline_user_data_job import (
    _make_capture_client_with_offline_user_data_job_service,
)
from tests.unit.test_run_offline_user_data_job import (
    _pool_with_transactable_conn as _pool_cm,
)

# ---------------------------------------------------------------------------
# R1-I1 — apply_change no caminho default devolve o motivo de cada falha
# ---------------------------------------------------------------------------


@pytest.fixture
def _ctx() -> Any:
    ctx = McpRequestContext(manager_id=uuid4(), session_id=uuid4())
    set_current(ctx)
    yield ctx
    clear_current()


def _saved(operation_type: str, payload: dict[str, Any]) -> MagicMock:
    saved = MagicMock()
    saved.operation_type = operation_type
    saved.customer_id = "1234567890"
    saved.blast_summary = "Remover 3 audience criteria do ad_group 42."
    saved.payload = payload
    return saved


async def _apply(resultado_do_run_mutation: dict[str, Any]) -> dict[str, Any]:
    """Roda `apply_change` no caminho DEFAULT (nem ad_schedule, nem recommendation)."""
    from src.mcp.tools import apply_change as mod

    saved = _saved(
        "remove_audience",
        {
            "target_type": "ad_group",
            "target_id": "42",
            "criterion_ids": ["1", "2", "3"],
            "__target_count__": 3,
            "__partial_failure__": True,
        },
    )
    with (
        patch.object(mod, "connection") as mock_conn,
        patch.object(mod, "consume", AsyncMock(return_value=saved)),
        patch.object(mod, "run_mutation", AsyncMock(return_value=resultado_do_run_mutation)),
    ):
        pool = MagicMock()
        mock_conn.get_pool.return_value = pool
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=None)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        out: dict[str, Any] = await mod.apply_change({"confirmation_token": "ABCD1234"})
    return out


@pytest.mark.asyncio
async def test_apply_change_default_devolve_o_motivo_de_cada_falha(_ctx: Any) -> None:
    """R1-I1: 5 tools operam em lote com `__partial_failure__`; quando o Google
    aceita parte, o motivo de cada recusa nao pode morrer no dispatcher.

    O ramo `update_ad_schedule` ja devolvia `partial_failures`; o default, por
    onde passam as outras cinco, nao — e a resposta dizia so "applied".
    """
    falhas = [
        {"index": 0, "status": "success", "error": None},
        {"index": 1, "status": "failed", "error": "RESOURCE_NOT_FOUND: criterion 2"},
        {"index": 2, "status": "failed", "error": "CONCURRENT_MODIFICATION"},
    ]
    out = await _apply(
        {
            "provider_request_id": "req-1",
            "applied_count": 1,
            "changed_count": 1,
            "partial_failures": falhas,
            "resource_names": ["customers/1234567890/adGroupCriteria/42~1", None, None],
        }
    )

    assert out["status"] == "applied"
    assert out["partial_failures"] == falhas, (
        "sem isto o gestor recebe 'applied' e nunca fica sabendo que 2 das 3 "
        "operacoes foram recusadas, nem por que"
    )
    assert out["failed_count"] == 2


@pytest.mark.asyncio
async def test_apply_change_default_sem_partial_failure_nao_inventa_falha(_ctx: Any) -> None:
    """Mutacao sem partial_failure mode: lista vazia e zero, nunca None/ausente."""
    out = await _apply(
        {
            "provider_request_id": "req-2",
            "applied_count": 1,
            "changed_count": 1,
            "partial_failures": [],
            "resource_names": ["customers/1234567890/campaigns/9"],
        }
    )
    assert out["partial_failures"] == []
    assert out["failed_count"] == 0


# ---------------------------------------------------------------------------
# R1-I2 — o audit do run_mutation grava o APLICADO, nao so o tentado
# ---------------------------------------------------------------------------


async def _rodar_mutation(
    monkeypatch: pytest.MonkeyPatch,
    per_op_errors: list[str | None],
    *,
    partial_failure: bool = True,
) -> tuple[dict[str, Any], AsyncMock]:
    from src.google_ads import mutations

    monkeypatch.setattr(mutations, "import_all_builders", lambda: None)
    monkeypatch.setattr(
        mutations,
        "get_builder",
        lambda _op: lambda c, cid, p: [MagicMock() for _ in per_op_errors],
    )
    monkeypatch.setattr(
        mutations,
        "build_client_for_manager",
        AsyncMock(return_value=_client_with_partial_failure(per_op_errors)),
    )
    monkeypatch.setattr(mutations, "get_request_id", lambda: "req-audit")

    audit = AsyncMock()
    with (
        patch(
            "src.google_ads.mutations.connection.get_pool",
            return_value=_pool_with_transactable_conn(),
        ),
        patch.object(mutations, "ensure_account_access", AsyncMock()),
        patch.object(mutations, "before_call", AsyncMock()),
        patch.object(mutations, "record_actual", AsyncMock()),
        patch("src.google_ads.mutations.audit_log.record", audit),
    ):
        result: dict[str, Any] = await mutations.run_mutation(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="add_negatives_from_search_terms",
            payload={"negatives": [{} for _ in per_op_errors]},
            target_count=len(per_op_errors),
            partial_failure=partial_failure,
        )
    return result, audit


@pytest.mark.asyncio
async def test_audit_do_run_mutation_registra_a_aplicacao_parcial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R1-I2: com 1 de 3 recusada, a linha de audit nao pode dizer so `target_count=3`.

    `target_count` e o TENTADO — sozinho ele afirma que as 3 passaram. O que
    de fato aconteceu vive em `params_summary["resultado"]`.
    """
    _, audit = await _rodar_mutation(monkeypatch, [None, "CRITERION_EXISTS", None])

    audit.assert_awaited_once()
    kwargs = audit.call_args.kwargs
    assert kwargs["target_count"] == 3, "o tentado continua sendo o tentado"
    resultado = kwargs["params_summary"]["resultado"]
    assert resultado["tentadas"] == 3
    assert resultado["aplicadas"] == 2
    assert resultado["falharam"] == 1
    assert resultado["indices_com_falha"] == [1]


@pytest.mark.asyncio
async def test_audit_nao_perde_o_params_summary_da_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O `resultado` entra AO LADO do resumo da tool, nunca no lugar dele."""
    from src.google_ads import mutations

    monkeypatch.setattr(mutations, "import_all_builders", lambda: None)
    monkeypatch.setattr(
        mutations, "get_builder", lambda _op: lambda c, cid, p: [MagicMock(), MagicMock()]
    )
    monkeypatch.setattr(
        mutations,
        "build_client_for_manager",
        AsyncMock(return_value=_client_with_partial_failure([None, "ERRO"])),
    )
    monkeypatch.setattr(mutations, "get_request_id", lambda: "req-audit")

    audit = AsyncMock()
    with (
        patch(
            "src.google_ads.mutations.connection.get_pool",
            return_value=_pool_with_transactable_conn(),
        ),
        patch.object(mutations, "ensure_account_access", AsyncMock()),
        patch.object(mutations, "before_call", AsyncMock()),
        patch.object(mutations, "record_actual", AsyncMock()),
        patch("src.google_ads.mutations.audit_log.record", audit),
    ):
        await mutations.run_mutation(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="add_negatives_from_search_terms",
            payload={"negatives": [{}, {}]},
            target_count=2,
            partial_failure=True,
            params_summary={"scopes_distribution": {"campaign": 2}},
        )

    ps = audit.call_args.kwargs["params_summary"]
    assert ps["scopes_distribution"] == {"campaign": 2}
    assert ps["resultado"]["falharam"] == 1


@pytest.mark.asyncio
async def test_audit_do_run_mutation_nao_vaza_o_texto_do_erro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """spec §3.6: a mensagem do Google ecoa o OPERANDO (o termo digitado).

    `params_summary` das tools de negativa exclui os termos de proposito; o
    resultado no audit carrega CONTAGEM e INDICE, nunca o texto do erro.
    """
    _, audit = await _rodar_mutation(
        monkeypatch, [None, "DUPLICATE_KEYWORD: 'comprar cimento barato'"]
    )
    ps = audit.call_args.kwargs["params_summary"]
    assert "cimento" not in str(ps)


# ---------------------------------------------------------------------------
# R1-I3 / R1-I4 — Customer Match
# ---------------------------------------------------------------------------


def _resposta_add_ops_com_falhas(client: Any, indices: dict[int, str]) -> MagicMock:
    """`AddOfflineUserDataJobOperationsResponse` com `partial_failure_error` populado.

    A resposta desse RPC NAO tem lista por-op: quem falhou so aparece pelo
    `field_path_elements[0].index` dentro do `GoogleAdsFailure`.
    """
    resp = MagicMock()
    if not indices:
        resp.partial_failure_error.code = 0
        resp.partial_failure_error.details = []
        return resp

    class _FakeError:
        def __init__(self, idx: int, msg: str) -> None:
            self.message = msg
            self.error_code = f"offline_user_data_job_error: {msg}"
            self.location = MagicMock()
            self.location.field_path_elements = [MagicMock(index=idx)]

    erros = [_FakeError(i, m) for i, m in indices.items()]

    def fake_unpack(target_pb: MagicMock) -> None:
        target_pb.errors = erros

    raw_any = MagicMock()
    raw_any.type_url = "type.googleapis.com/google.ads.googleads.v24.errors.GoogleAdsFailure"
    raw_any.Unpack = fake_unpack
    detail = MagicMock()
    detail._pb = raw_any

    resp.partial_failure_error.code = 3
    resp.partial_failure_error.details = [detail]

    stub = MagicMock()
    stub._meta.pb = lambda: MagicMock(errors=[])
    _original_get_type = client.get_type

    def _get_type(name: str) -> Any:
        if name == "GoogleAdsFailure":
            return stub
        return _original_get_type(name)

    client.get_type = _get_type
    return resp


async def _rodar_job(
    *,
    recusados: dict[int, str] | None = None,
    falha_em: str | None = None,
    membros: int = 3,
) -> tuple[dict[str, Any] | None, AsyncMock, Exception | None]:
    """Roda o dispatcher com o MESMO client que o `_rodar_job` de producao usa.

    `recusados` (indice -> mensagem) e montado CONTRA esse client: o stub de
    `GoogleAdsFailure` precisa viver no `get_type` dele, senao o
    desempacotamento cai no ramo de erro e o teste passa por engano.
    """
    from src.google_ads.customer_match import run_offline_user_data_job

    client, service = _make_capture_client_with_offline_user_data_job_service()
    if recusados is not None:
        service.add_offline_user_data_job_operations = MagicMock(
            return_value=_resposta_add_ops_com_falhas(client, recusados)
        )
    if falha_em is not None:
        setattr(service, falha_em, MagicMock(side_effect=RuntimeError("boom da API")))

    audit = AsyncMock(return_value=1)
    out: dict[str, Any] | None = None
    erro: Exception | None = None
    with (
        patch(
            "src.google_ads.customer_match.build_client_for_manager",
            AsyncMock(return_value=client),
        ),
        patch(
            "src.google_ads.customer_match.connection.get_pool",
            return_value=_pool_cm(),
        ),
        patch("src.google_ads.customer_match.ensure_account_access", AsyncMock()),
        patch("src.google_ads.customer_match.before_call", AsyncMock()),
        patch("src.google_ads.customer_match.record_actual", AsyncMock()),
        patch("src.google_ads.customer_match.audit_log.record", audit),
    ):
        try:
            out = await run_offline_user_data_job(
                manager_id=uuid4(),
                session_id=uuid4(),
                customer_id="1163862076",
                user_list_id="1234567890",
                operation_type="add",
                hashed_members=[{"hashed_email": f"h{i}"} for i in range(membros)],
            )
        except Exception as e:  # noqa: BLE001 — o teste decide o que fazer com ela
            erro = e
    return out, audit, erro


@pytest.mark.asyncio
async def test_customer_match_nao_reporta_como_submetido_o_que_o_google_recusou() -> None:
    """R1-I3: `enable_partial_failure=True` e a resposta ia pro lixo.

    Com 1 de 3 membros recusado, `members_submitted: 3` e falso — e e o unico
    numero que o gestor ve.
    """
    out, _, erro = await _rodar_job(recusados={1: "INVALID_SHA256_FORMAT"}, membros=3)

    assert erro is None
    assert out is not None
    assert out["members_submitted"] == 2, "o recusado nao foi submetido"
    assert out["members_failed"] == 1
    assert out["failures"] == [
        {
            "index": 1,
            "error_message": "INVALID_SHA256_FORMAT",
            "error_code": "INVALID_SHA256_FORMAT",
        }
    ]


@pytest.mark.asyncio
async def test_customer_match_lote_inteiro_aceito_nao_inventa_falha() -> None:
    out, _, erro = await _rodar_job(recusados={}, membros=3)

    assert erro is None
    assert out is not None
    assert out["members_submitted"] == 3
    assert out["members_failed"] == 0
    assert out["failures"] == []


@pytest.mark.asyncio
async def test_customer_match_audit_de_erro_aponta_a_etapa_e_o_job() -> None:
    """R1-I4: falha no passo 3 (run) DEPOIS do passo 2 (add) deixa PII anexada
    no Google. O audit precisa carregar o identificador que aponta pra ela.

    O codigo pre-fix gravava `provider_request_id=""` — contradizendo o proprio
    comentario ao lado, que prometia "o ultimo request-id bem-sucedido, util no
    audit de erro pra saber em qual das 3 etapas parou".
    """
    _, audit, erro = await _rodar_job(falha_em="run_offline_user_data_job", membros=2)

    assert erro is not None
    audit.assert_awaited_once()
    kwargs = audit.call_args.kwargs
    assert kwargs["status"] == "error"
    assert kwargs["provider_request_id"], (
        "audit de erro sem provider_request_id nao aponta pro que ficou no Google"
    )
    ps = kwargs["params_summary"]
    assert ps["etapa"] == "run_job", "a trilha tem que dizer ONDE parou"
    assert ps["job_resource_name"].endswith("/offlineUserDataJobs/JOB123")
    assert ps["pii_anexada"] is True, (
        "passo 2 concluido = os membros ja estao no Google; a trilha tem que dizer isso"
    )


@pytest.mark.asyncio
async def test_customer_match_falha_no_passo_1_nao_afirma_pii_anexada() -> None:
    """Controle: sem o passo 2, nada foi anexado — e a trilha nao pode dizer que foi."""
    _, audit, erro = await _rodar_job(falha_em="create_offline_user_data_job", membros=2)

    assert erro is not None
    ps = audit.call_args.kwargs["params_summary"]
    assert ps["etapa"] == "create_job"
    assert ps["pii_anexada"] is False
    assert ps["job_resource_name"] is None


@pytest.mark.asyncio
async def test_customer_match_audit_de_erro_nunca_carrega_hash() -> None:
    """LGPD: o resumo ganhou campos novos — nenhum deles pode trazer o hash."""
    _, audit, _ = await _rodar_job(falha_em="add_offline_user_data_job_operations", membros=2)
    assert "h0" not in str(audit.call_args.kwargs["params_summary"])


# ---------------------------------------------------------------------------
# O leitor compartilhado nao pode tornar o caminho de mutate mais fragil
# ---------------------------------------------------------------------------


def _failure_com(erros: list[Any], client: MagicMock) -> MagicMock:
    def fake_unpack(target_pb: MagicMock) -> None:
        target_pb.errors = erros

    raw_any = MagicMock()
    raw_any.type_url = "type.googleapis.com/google.ads.googleads.v24.errors.GoogleAdsFailure"
    raw_any.Unpack = fake_unpack
    detail = MagicMock()
    detail._pb = raw_any

    resp = MagicMock()
    resp.partial_failure_error.code = 3
    resp.partial_failure_error.details = [detail]

    stub = MagicMock()
    stub._meta.pb = lambda: MagicMock(errors=[])
    client.get_type = MagicMock(return_value=stub)
    return resp


class _ErroSemCodigo:
    """Erro cujo `error_code` nao esta la — a forma que os fakes de 3 suites usam."""

    def __init__(self, idx: int, msg: str) -> None:
        self.message = msg
        self.location = MagicMock()
        self.location.field_path_elements = [MagicMock(index=idx)]


def test_erro_sem_codigo_nao_derruba_a_mensagem() -> None:
    """`run_mutation` sempre leu so `message` e `location`.

    Quando as tres leitoras passaram a compartilhar o desempacotamento, um
    acesso duro a `error_code` fez o `except` engolir o LOTE inteiro: o caminho
    de mutate perdia todos os motivos por causa de um campo que ele nem usa.
    Trocar "sem codigo" por "sem motivo nenhum" e uma regressao de robustez
    escondida dentro de um refactor.
    """
    from src.google_ads.partial_failure import erros_por_indice

    client = MagicMock()
    resp = _failure_com([_ErroSemCodigo(1, "CRITERION_EXISTS")], client)

    erros = erros_por_indice(resp, client, origem="teste")
    assert erros[1].error_message == "CRITERION_EXISTS"
    assert erros[1].error_code == "UNKNOWN"


def test_sem_falha_nenhuma_devolve_mapa_vazio() -> None:
    from src.google_ads.partial_failure import erros_por_indice

    resp = MagicMock()
    resp.partial_failure_error.code = 0
    resp.partial_failure_error.details = []
    assert erros_por_indice(resp, MagicMock(), origem="teste") == {}
