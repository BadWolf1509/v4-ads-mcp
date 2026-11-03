"""Caracterizacao do `apply_change` antes de ele virar despachante (Task G5).

`apply_change` e o caminho de TODA escrita confirmada em producao. A refatoracao
nao pode mudar comportamento nenhum, e estes testes prendem o que o codigo FAZ
hoje — nao o que deveria fazer — para cada ramo e para o padrao:

- a ORDEM: consumo do token -> pre-check (quando ha) -> escrita -> pos-check
  (quando ha). O consumo vem ANTES do pre-check: um pre-check que recusa ja
  encontrou o token consumido, e o gestor precisa de um token novo (a mensagem de
  recusa diz isso);
- a escrita sai UMA vez, sem retry, com os mesmos kwargs;
- pre-check que recusa nao escreve; pre-check que levanta propaga (nada mutou,
  entao propagar e o lado seguro);
- falha de I/O no pos-check devolve sucesso com o aviso atual (F83/F91);
- o envelope de cada ramo sai IGUAL, campo a campo (F182: `partial_failure`,
  `failed_count: null`, `motivos_medidos`).

Os fakes registram cada passo numa trilha unica; a comparacao e da trilha
inteira, entao passo a mais (retry, I/O depois da escrita) tambem quebra.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from src.db import connection
from src.governance.dry_run import InvalidTokenError
from src.mcp.context import McpRequestContext, clear_current, set_current
from src.mcp.tools import apply_change as mod

_CID = "1234567890"
_REC_RN = f"customers/{_CID}/recommendations/abc"
_MANAGER = UUID("00000000-0000-0000-0000-00000000000a")
_SESSION = UUID("00000000-0000-0000-0000-00000000000b")


@pytest.fixture(autouse=True)
def _ctx() -> Any:
    set_current(McpRequestContext(manager_id=_MANAGER, session_id=_SESSION))
    yield
    clear_current()


class _FakeConn:
    async def __aenter__(self) -> _FakeConn:
        return self

    async def __aexit__(self, *a: Any) -> bool:
        return False


class _FakePool:
    def acquire(self) -> _FakeConn:
        return _FakeConn()


def _janela() -> dict[str, Any]:
    return {
        "day_of_week": "MONDAY",
        "start_hour": 7,
        "start_minute": 0,
        "end_hour": 17,
        "end_minute": 0,
    }


def _row_schedule(crit: str = "10", status: str = "ENABLED") -> dict[str, Any]:
    return {
        "campaign_id": "1",
        "campaign_name": "A",
        "criterion_id": crit,
        "resource_name": f"customers/{_CID}/campaignCriteria/1~{crit}",
        "day_of_week": "MONDAY",
        "start_hour": 7,
        "start_minute": 0,
        "end_hour": 17,
        "end_minute": 0,
        "bid_modifier": None,
        "status": status,
    }


def _impressao(recomendado: float = 180.0) -> dict[str, Any]:
    return {
        "type": "CAMPAIGN_BUDGET",
        "current_amount_brl": 50.0,
        "recommended_amount_brl": recomendado,
        "valores": {},
    }


def _row_rec(recomendado: float = 180.0) -> dict[str, Any]:
    imp = _impressao(recomendado)
    return {
        "resource_name": _REC_RN,
        "type": imp["type"],
        "type_pt": None,
        "campaign_resource_name": "",
        "campaign_id": None,
        "current_amount_brl": imp["current_amount_brl"],
        "recommended_amount_brl": imp["recommended_amount_brl"],
        "valores": imp["valores"],
    }


def _payloads() -> dict[str, tuple[str, dict[str, Any]]]:
    """(operation_type, payload) por ramo. `padrao_*` cai no caminho default."""
    return {
        "import_offline_conversions": (
            "import_offline_conversions",
            {
                "conversion_action_id": "987",
                "conversions": [],
                "__target_count__": 5,
                "__params_summary__": {"conversion_count": 5},
            },
        ),
        "apply_recommendation": (
            "apply_recommendation",
            {
                "recommendation_resource_name": _REC_RN,
                "__target_count__": 1,
                "valores_do_preview": _impressao(),
            },
        ),
        "upload_customer_match_list": (
            "upload_customer_match_list",
            {"user_list_id": "999", "operation": "add", "hashed_members": [{"hashed_email": "h0"}]},
        ),
        "update_ad_schedule": (
            "update_ad_schedule",
            {
                "campaign_ids": ["1"],
                "windows": [_janela()],
                "windows_bid_modifiers": [None],
                "current_keys": {"1": []},
                "ops": [
                    {"kind": "add", "campaign_id": "1", "window": _janela(), "bid_modifier": None}
                ],
                "__target_count__": 1,
                "__partial_failure__": True,
                "__params_summary__": {"x": 1},
            },
        ),
        "padrao_sem_flag": (
            "create_ad_group",
            {"ad_groups": [{}, {}], "__target_count__": 2},
        ),
        "padrao_com_flag": (
            "remove_audience",
            {
                "criterion_ids": ["1", "2"],
                "__target_count__": 2,
                "__partial_failure__": True,
                "__params_summary__": {"y": 2},
            },
        ),
    }


_RESULTADOS: dict[str, dict[str, Any]] = {
    "run_conversion_upload": {
        "status": "applied",
        "applied_count": 4,
        "failed_count": 1,
        "failures": [{"index": 3, "error": "x"}],
        "provider_request_id": "req-conv",
        "motivos_medidos": True,
    },
    "run_recommendation_action": {"applied_count": 1, "provider_request_id": "req-rec"},
    "run_offline_user_data_job": {
        "job_resource_name": f"customers/{_CID}/offlineUserDataJobs/JOB123",
        "provider_request_id_create_job": "req-c",
        "provider_request_id_add_ops": "req-a",
        "provider_request_id_run_job": "req-r",
        "members_submitted": 1,
        "members_failed": 0,
        "failures": [],
        "recusas_medidas": True,
    },
    "run_mutation": {
        "provider_request_id": "req-mut",
        "applied_count": 2,
        "changed_count": 1,
        "partial_failures": [
            {"index": 0, "status": "success", "error": None, "efeito": "mudou"},
            {"index": 1, "status": "failed", "error": None, "efeito": None},
        ],
        "resource_names": ["customers/1/x/1", None],
        "motivos_medidos": False,
    },
}


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    ramo: str,
    *,
    token_invalido: bool = False,
    rec_linhas: list[dict[str, Any]] | None = None,
    schedule_antes: list[dict[str, Any]] | None = None,
    pre_check_explode: bool = False,
    escrita_explode: bool = False,
    pos_check_explode: bool = False,
    resultado: dict[str, Any] | None = None,
) -> tuple[list[tuple[str, ...]], dict[str, list[dict[str, Any]]], SimpleNamespace]:
    operation_type, payload = _payloads()[ramo]
    saved = SimpleNamespace(
        operation_type=operation_type,
        customer_id=_CID,
        blast_summary=f"resumo de {ramo}",
        payload=payload,
    )
    trilha: list[tuple[str, ...]] = []
    kwargs_escrita: dict[str, list[dict[str, Any]]] = {}

    async def _consume(conn: Any, *, token: str, session_id: Any) -> SimpleNamespace:
        trilha.append(("consumo", token, str(session_id)))
        if token_invalido:
            raise InvalidTokenError(f"Token '{token}' already consumed")
        return saved

    async def _run_report(**kw: Any) -> list[dict[str, Any]]:
        nome = kw["operation_name"]
        fase = "pos_check" if nome.endswith("_confirm") else "pre_check"
        trilha.append((fase, nome))
        assert kw["manager_id"] == _MANAGER and kw["session_id"] == _SESSION
        assert kw["customer_id"] == _CID
        if fase == "pre_check" and pre_check_explode:
            raise RuntimeError("pre-check caiu")
        if fase == "pos_check" and pos_check_explode:
            raise ConnectionError("pos-check caiu")
        if nome == "apply_recommendation_precheck":
            return [_row_rec()] if rec_linhas is None else rec_linhas
        if nome == "update_ad_schedule_precheck":
            return [] if schedule_antes is None else schedule_antes
        assert nome == "update_ad_schedule_confirm", nome
        return [_row_schedule()]

    def _escrita(nome: str) -> Any:
        async def _f(**kw: Any) -> dict[str, Any]:
            trilha.append(("escrita", nome))
            kwargs_escrita.setdefault(nome, []).append(kw)
            if escrita_explode:
                raise RuntimeError("escrita caiu")
            return resultado if resultado is not None else _RESULTADOS[nome]

        return _f

    monkeypatch.setattr(mod, "consume", _consume)
    monkeypatch.setattr(mod, "run_report", _run_report)
    monkeypatch.setattr(mod, "run_mutation", _escrita("run_mutation"))
    monkeypatch.setattr(mod, "run_conversion_upload", _escrita("run_conversion_upload"))
    monkeypatch.setattr(mod, "run_recommendation_action", _escrita("run_recommendation_action"))
    monkeypatch.setattr(
        "src.google_ads.customer_match.run_offline_user_data_job",
        _escrita("run_offline_user_data_job"),
    )
    monkeypatch.setattr(connection, "get_pool", lambda: _FakePool())
    return trilha, kwargs_escrita, saved


_TOKEN = "ABCD1234"
_CONSUMO = ("consumo", _TOKEN, str(_SESSION))

# Trilha esperada no caminho feliz, por ramo.
_TRILHA_FELIZ: dict[str, list[tuple[str, ...]]] = {
    "import_offline_conversions": [_CONSUMO, ("escrita", "run_conversion_upload")],
    "apply_recommendation": [
        _CONSUMO,
        ("pre_check", "apply_recommendation_precheck"),
        ("escrita", "run_recommendation_action"),
    ],
    "upload_customer_match_list": [_CONSUMO, ("escrita", "run_offline_user_data_job")],
    "update_ad_schedule": [
        _CONSUMO,
        ("pre_check", "update_ad_schedule_precheck"),
        ("escrita", "run_mutation"),
        ("pos_check", "update_ad_schedule_confirm"),
    ],
    "padrao_sem_flag": [_CONSUMO, ("escrita", "run_mutation")],
    "padrao_com_flag": [_CONSUMO, ("escrita", "run_mutation")],
}

_RAMOS = list(_TRILHA_FELIZ)


def _kwargs_esperados(ramo: str, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    base = {"manager_id": _MANAGER, "session_id": _SESSION, "customer_id": _CID}
    op = _payloads()[ramo][0]
    if ramo == "import_offline_conversions":
        return "run_conversion_upload", {
            **base,
            "operation_type": op,
            "payload": payload,
            "target_count": 5,
            "params_summary": {"conversion_count": 5},
        }
    if ramo == "apply_recommendation":
        return "run_recommendation_action", {**base, "operation_type": op, "payload": payload}
    if ramo == "upload_customer_match_list":
        return "run_offline_user_data_job", {
            **base,
            "user_list_id": "999",
            "operation_type": "add",
            "hashed_members": [{"hashed_email": "h0"}],
        }
    if ramo == "update_ad_schedule":
        return "run_mutation", {
            **base,
            "operation_type": op,
            "payload": payload,
            "target_count": 1,
            "partial_failure": True,
            "params_summary": {"x": 1},
        }
    if ramo == "padrao_sem_flag":
        return "run_mutation", {
            **base,
            "operation_type": op,
            "payload": payload,
            "target_count": 2,
            "partial_failure": False,
            "params_summary": None,
        }
    return "run_mutation", {
        **base,
        "operation_type": op,
        "payload": payload,
        "target_count": 2,
        "partial_failure": True,
        "params_summary": {"y": 2},
    }


_MUT = _RESULTADOS["run_mutation"]

_ENVELOPE_FELIZ: dict[str, dict[str, Any]] = {
    "import_offline_conversions": {
        "status": "applied",
        "operation": "import_offline_conversions",
        "customer_id": _CID,
        "blast_summary": "resumo de import_offline_conversions",
        "applied_count": 4,
        "provider_request_id": "req-conv",
        "failed_count": 1,
        "failures": [{"index": 3, "error": "x"}],
        "motivos_medidos": True,
    },
    "apply_recommendation": {
        "status": "applied",
        "operation": "apply_recommendation",
        "customer_id": _CID,
        "blast_summary": "resumo de apply_recommendation",
        "applied_count": 1,
        "provider_request_id": "req-rec",
    },
    "upload_customer_match_list": {
        "status": "submitted",
        "operation": "upload_customer_match_list",
        "customer_id": _CID,
        "blast_summary": "resumo de upload_customer_match_list",
        "user_list_id": "999",
        "operation_type": "add",
        "members_submitted": 1,
        "members_failed": 0,
        "failures": [],
        "recusas_medidas": True,
        "job_resource_name": f"customers/{_CID}/offlineUserDataJobs/JOB123",
        "provider_request_id_create_job": "req-c",
        "provider_request_id_add_ops": "req-a",
        "provider_request_id_run_job": "req-r",
        "to_check_status": (
            "Job é assíncrono no backend Google (processa em horas). Pra verificar "
            "status, use run_gaql com query 'SELECT offline_user_data_job.status, "
            "offline_user_data_job.failure_reason FROM offline_user_data_job WHERE "
            "offline_user_data_job.id = JOB123'."
        ),
    },
    "update_ad_schedule": {
        "status": "applied",
        "operation": "update_ad_schedule",
        "customer_id": _CID,
        "blast_summary": "resumo de update_ad_schedule",
        "applied_count": 2,
        "provider_request_id": "req-mut",
        "changed_count": 1,
        "partial_failure": True,
        "failed_count": 1,
        "partial_failures": _MUT["partial_failures"],
        "resource_names": _MUT["resource_names"],
        "resulting_schedule": {
            "1": {
                "has_schedule": True,
                "windows_count": 1,
                "hours_per_week": 10.0,
                "windows": [_row_schedule()],
                "matches_requested": True,
                "truncated": False,
            }
        },
        "confirmation_error": None,
        "motivos_medidos": False,
    },
    "padrao_sem_flag": {
        "status": "applied",
        "operation": "create_ad_group",
        "customer_id": _CID,
        "blast_summary": "resumo de padrao_sem_flag",
        "applied_count": 2,
        "provider_request_id": "req-mut",
        "changed_count": 1,
        "partial_failure": False,
        "partial_failures": _MUT["partial_failures"],
        # F182: flag desligada -> NAO medido, nunca 0.
        "failed_count": None,
        "resource_names": _MUT["resource_names"],
        "motivos_medidos": False,
    },
    "padrao_com_flag": {
        "status": "applied",
        "operation": "remove_audience",
        "customer_id": _CID,
        "blast_summary": "resumo de padrao_com_flag",
        "applied_count": 2,
        "provider_request_id": "req-mut",
        "changed_count": 1,
        "partial_failure": True,
        "partial_failures": _MUT["partial_failures"],
        "failed_count": 1,
        "resource_names": _MUT["resource_names"],
        "motivos_medidos": False,
    },
}


@pytest.mark.asyncio
@pytest.mark.parametrize("ramo", _RAMOS)
async def test_caminho_feliz_ordem_kwargs_e_envelope(
    monkeypatch: pytest.MonkeyPatch, ramo: str
) -> None:
    """Consumo -> pre-check -> escrita (uma vez) -> pos-check, e o envelope inteiro."""
    trilha, kwargs_escrita, saved = _wire(monkeypatch, ramo)
    out = await mod.apply_change({"confirmation_token": _TOKEN})

    assert trilha == _TRILHA_FELIZ[ramo]
    nome, esperado = _kwargs_esperados(ramo, saved.payload)
    assert kwargs_escrita == {nome: [esperado]}
    assert out == _ENVELOPE_FELIZ[ramo]
    # Ordem das chaves tambem e contrato observavel (JSON serializado).
    assert list(out) == list(_ENVELOPE_FELIZ[ramo])


@pytest.mark.asyncio
@pytest.mark.parametrize("ramo", _RAMOS)
async def test_token_invalido_nao_chega_ao_pre_check_nem_a_escrita(
    monkeypatch: pytest.MonkeyPatch, ramo: str
) -> None:
    trilha, kwargs_escrita, _ = _wire(monkeypatch, ramo, token_invalido=True)
    out = await mod.apply_change({"confirmation_token": _TOKEN})
    assert trilha == [_CONSUMO]
    assert kwargs_escrita == {}
    assert out == {
        "status": "error",
        "error_message": f"Token '{_TOKEN}' already consumed",
        "operation": "apply_change",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("ramo", _RAMOS)
async def test_escrita_que_falha_propaga_sem_retry_e_sem_pos_check(
    monkeypatch: pytest.MonkeyPatch, ramo: str
) -> None:
    """Sem retry de mutacao: a escrita sai uma vez e a excecao sobe como hoje."""
    trilha, _, _ = _wire(monkeypatch, ramo, escrita_explode=True)
    with pytest.raises(RuntimeError, match="escrita caiu"):
        await mod.apply_change({"confirmation_token": _TOKEN})
    feliz = _TRILHA_FELIZ[ramo]
    ate_escrita = feliz[: [p[0] for p in feliz].index("escrita") + 1]
    assert trilha == ate_escrita


# --- pre-check que recusa: nao escreve; o token ja foi consumido -------------------

_RECUSA_REC_SEM_IMPRESSAO = (
    "Este token foi emitido por uma versao anterior da tool e nao carrega "
    "os valores previstos, entao nao da pra conferir se a recomendacao "
    "mudou. Nada foi aplicado. Refaca o apply_recommendation para gerar "
    "um token novo."
)


@pytest.mark.asyncio
async def test_recomendacao_sem_impressao_recusa_sem_ler_nem_escrever(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trilha, kwargs_escrita, saved = _wire(monkeypatch, "apply_recommendation")
    del saved.payload["valores_do_preview"]
    out = await mod.apply_change({"confirmation_token": _TOKEN})
    assert trilha == [_CONSUMO]
    assert kwargs_escrita == {}
    assert out == {
        "status": "error",
        "error_message": _RECUSA_REC_SEM_IMPRESSAO,
        "operation": "apply_recommendation",
        "customer_id": _CID,
    }


@pytest.mark.asyncio
async def test_recomendacao_que_sumiu_recusa_sem_escrever(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trilha, kwargs_escrita, _ = _wire(monkeypatch, "apply_recommendation", rec_linhas=[])
    out = await mod.apply_change({"confirmation_token": _TOKEN})
    assert trilha == [_CONSUMO, ("pre_check", "apply_recommendation_precheck")]
    assert kwargs_escrita == {}
    assert out == {
        "status": "error",
        "error_message": (
            f"A recomendacao {_REC_RN} nao esta mais pendente na conta {_CID} (aplicada, "
            "dispensada ou expirada desde o preview). Nada foi aplicado. Use "
            "get_recommendations para ver o que resta."
        ),
        "operation": "apply_recommendation",
        "customer_id": _CID,
    }


@pytest.mark.asyncio
async def test_recomendacao_revisada_recusa_sem_escrever(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trilha, kwargs_escrita, _ = _wire(
        monkeypatch, "apply_recommendation", rec_linhas=[_row_rec(300.0)]
    )
    out = await mod.apply_change({"confirmation_token": _TOKEN})
    assert trilha == [_CONSUMO, ("pre_check", "apply_recommendation_precheck")]
    assert kwargs_escrita == {}
    assert out["status"] == "error"
    assert out["operation"] == "apply_recommendation"
    assert out["customer_id"] == _CID
    assert list(out) == ["status", "error_message", "operation", "customer_id"]
    assert out["error_message"].startswith(
        "O Google revisou esta recomendacao desde o preview — o valor que voce "
        "confirmou nao e mais o que seria aplicado ("
    )
    assert "180.0 -> 300.0" in out["error_message"]
    assert out["error_message"].endswith(
        "). Nada foi aplicado. Refaca o apply_recommendation para ver o valor atual "
        "e gerar um token novo."
    )


@pytest.mark.asyncio
async def test_grade_mudada_recusa_sem_escrever(monkeypatch: pytest.MonkeyPatch) -> None:
    trilha, kwargs_escrita, _ = _wire(
        monkeypatch, "update_ad_schedule", schedule_antes=[_row_schedule(crit="12")]
    )
    out = await mod.apply_change({"confirmation_token": _TOKEN})
    assert trilha == [_CONSUMO, ("pre_check", "update_ad_schedule_precheck")]
    assert kwargs_escrita == {}
    assert out == {
        "status": "error",
        "error_message": (
            "A grade mudou desde o preview (alguem alterou a agenda destas campanhas "
            "nos ultimos minutos). Nenhuma operacao foi aplicada. Refaca o "
            "update_ad_schedule para gerar um token novo sobre o estado atual."
        ),
        "operation": "update_ad_schedule",
        "customer_id": _CID,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("ramo", ["apply_recommendation", "update_ad_schedule"])
async def test_pre_check_que_levanta_propaga_sem_escrever(
    monkeypatch: pytest.MonkeyPatch, ramo: str
) -> None:
    """Read ANTES da escrita: propagar e o lado seguro (nada mutou). Hoje nao ha
    tratamento — a excecao sobe, depois do token ja consumido."""
    trilha, kwargs_escrita, _ = _wire(monkeypatch, ramo, pre_check_explode=True)
    with pytest.raises(RuntimeError, match="pre-check caiu"):
        await mod.apply_change({"confirmation_token": _TOKEN})
    assert trilha == _TRILHA_FELIZ[ramo][:2]
    assert kwargs_escrita == {}


# --- pos-check: I/O depois da escrita nunca vira erro (F83/F91) ---------------------


@pytest.mark.asyncio
async def test_pos_check_que_falha_devolve_sucesso_com_o_aviso(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trilha, kwargs_escrita, _ = _wire(monkeypatch, "update_ad_schedule", pos_check_explode=True)
    out = await mod.apply_change({"confirmation_token": _TOKEN})
    assert trilha == _TRILHA_FELIZ["update_ad_schedule"]
    assert len(kwargs_escrita["run_mutation"]) == 1
    esperado = {
        **_ENVELOPE_FELIZ["update_ad_schedule"],
        "resulting_schedule": None,
        "confirmation_error": (
            "A mutacao foi aplicada (veja applied_count/provider_request_id), mas a "
            "reconsulta da grade falhou (ConnectionError). Confirme o estado com "
            "get_ad_schedule antes de confiar no resultado."
        ),
    }
    assert out == esperado
    assert list(out) == list(esperado)


@pytest.mark.asyncio
async def test_conversao_com_erro_do_executor_volta_como_veio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O ramo de conversoes devolve o envelope de erro do executor sem reembalar."""
    erro = {"status": "error", "error_message": "quota", "operation": "import_offline_conversions"}
    trilha, _, _ = _wire(monkeypatch, "import_offline_conversions", resultado=erro)
    out = await mod.apply_change({"confirmation_token": _TOKEN})
    assert out is erro
    assert trilha == _TRILHA_FELIZ["import_offline_conversions"]


@pytest.mark.asyncio
async def test_sessao_do_contexto_e_a_que_consome(monkeypatch: pytest.MonkeyPatch) -> None:
    """O token e amarrado a sessao MCP: o consumo recebe a sessao do contexto."""
    outra = uuid4()
    set_current(McpRequestContext(manager_id=_MANAGER, session_id=outra))
    trilha, _, _ = _wire(monkeypatch, "padrao_sem_flag", token_invalido=True)
    await mod.apply_change({"confirmation_token": _TOKEN})
    assert trilha == [("consumo", _TOKEN, str(outra))]
