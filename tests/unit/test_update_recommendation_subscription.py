"""update_recommendation_subscription (N3): pausa e reativa assinatura de auto-apply.

Medido na MO-JP (7862230676) em 14/11: `FROM recommendation_subscription` devolve 11
tipos; `RESPONSIVE_SEARCH_AD` ENABLED desde 06/06/2024 e a UI nao o lista (F185) — so
a API pausa. Quatro linhas vem com `type = UNKNOWN` e o MESMO `resource_name`
`.../recommendationSubscriptions/UNKNOWN`: nao sao enderecaveis, e a tool recusa.

**Os fakes montam a row com o proto de verdade** (`RecommendationSubscription`), so
com os campos que o SELECT pediu (mesmo padrao de `test_apply_recommendation.py`):
proto-plus devolve o zero-value para campo fora do SELECT (F145), entao um dict
pronto passaria verde com o `status` fora da query.
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import jsonschema
import pytest
from google.ads.googleads.v25.enums.types.recommendation_subscription_status import (
    RecommendationSubscriptionStatusEnum,
)
from google.ads.googleads.v25.enums.types.recommendation_type import RecommendationTypeEnum
from google.ads.googleads.v25.resources.types.recommendation_subscription import (
    RecommendationSubscription,
)

from src.db import connection
from src.google_ads.mutates.recommendation_subscriptions import (
    build_update_recommendation_subscription,
)
from src.google_ads.queries.recommendation_subscription import (
    TIPOS_ASSINAVEIS,
    assinatura_query,
)
from src.governance.blast_radius import RiskLevel, classify
from src.mcp.tools import update_recommendation_subscription as mod
from tests.unit.fixtures.fake_pool import FakePool
from tests.unit.fixtures.proto_capture import make_capture_client

_CID = "7862230676"


def _campos_do_select(query: str) -> set[str]:
    m = re.search(r"\bSELECT\b(.+?)\bFROM\b", query, re.S | re.I)
    assert m is not None, f"GAQL sem SELECT..FROM: {query!r}"
    return {c.strip() for c in m.group(1).split(",") if c.strip()}


def linha_de_assinatura(query: str, tipo: str, status: str | None) -> Any:
    """Row real do proto, so com o que o SELECT pediu.

    `status=None` deixa o campo no default do proto (0, UNSPECIFIED): e o que chega
    quando o Google omite o campo — "nao lido", nao um status medido.
    """
    pedidos = _campos_do_select(query)
    sub = RecommendationSubscription()
    if "recommendation_subscription.type" in pedidos:
        sub.type_ = RecommendationTypeEnum.RecommendationType[tipo]
    if "recommendation_subscription.status" in pedidos and status is not None:
        sub.status = RecommendationSubscriptionStatusEnum.RecommendationSubscriptionStatus[status]
    if "recommendation_subscription.modify_date_time" in pedidos:
        sub.modify_date_time = "2024-06-06 10:17:54.382095"
    return SimpleNamespace(recommendation_subscription=sub)


@pytest.fixture(autouse=True)
def _ctx() -> Any:
    from src.mcp.context import McpRequestContext, clear_current, set_current

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _wire(monkeypatch: pytest.MonkeyPatch, linhas: list[tuple[str, str]]) -> dict[str, Any]:
    capturado: dict[str, Any] = {"queries": [], "pending": None}

    async def _run(**kwargs: Any) -> list[dict[str, Any]]:
        q: str = kwargs["query"]
        capturado["queries"].append(q)
        capturado["operation_name"] = kwargs["operation_name"]
        fmt = kwargs["row_formatter"]
        return [fmt(linha_de_assinatura(q, t, s)) for t, s in linhas]

    async def _create_pending(conn: Any, **kwargs: Any) -> str:
        capturado["pending"] = kwargs
        return "TOKEN123"

    monkeypatch.setattr(mod, "run_report", _run)
    monkeypatch.setattr("src.mcp.tools._mutate_common.create_pending", _create_pending)
    monkeypatch.setattr(connection, "get_pool", lambda: FakePool())
    return capturado


async def _chamar(tipo: str, status: str) -> dict[str, Any]:
    out: dict[str, Any] = await mod.update_recommendation_subscription(
        {"customer_id": _CID, "type": tipo, "status": status}
    )
    return out


# --------------------------------------------------------------------------- #
# Enum e schema
# --------------------------------------------------------------------------- #
def test_tipos_derivados_do_enum() -> None:
    nomes = set(RecommendationTypeEnum.RecommendationType.__members__)
    assert set(TIPOS_ASSINAVEIS) == nomes - {"UNKNOWN", "UNSPECIFIED"}
    assert "RESPONSIVE_SEARCH_AD" in TIPOS_ASSINAVEIS


def test_schema_e_o_do_contrato() -> None:
    schema = mod._SCHEMA
    assert schema["required"] == ["customer_id", "type", "status"]
    assert schema["properties"]["customer_id"]["pattern"] == "^[0-9]{10}$"
    assert schema["properties"]["status"]["enum"] == ["PAUSED", "ENABLED"]
    assert set(schema["properties"]["type"]["enum"]) == set(TIPOS_ASSINAVEIS)


@pytest.mark.parametrize("tipo", ["UNKNOWN", "UNSPECIFIED"])
def test_unknown_recusado_no_schema(tipo: str) -> None:
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"customer_id": _CID, "type": tipo, "status": "PAUSED"}, mod._SCHEMA)


async def test_unknown_recusado_na_tool_sem_ler(monkeypatch: pytest.MonkeyPatch) -> None:
    """Segunda barreira: a tool nao confia so no schema (F185, nome degenerado)."""
    cap = _wire(monkeypatch, [("RESPONSIVE_SEARCH_AD", "ENABLED")])
    out = await _chamar("UNKNOWN", "PAUSED")
    assert out["status"] == "error"
    assert "F185" in out["error_message"]
    assert cap["queries"] == []
    assert cap["pending"] is None


# --------------------------------------------------------------------------- #
# Dry-run: recusas e no-op
# --------------------------------------------------------------------------- #
async def test_tipo_sem_assinatura_recusa(monkeypatch: pytest.MonkeyPatch) -> None:
    cap = _wire(monkeypatch, [])
    out = await _chamar("KEYWORD", "ENABLED")
    assert out["status"] == "error"
    assert "criar assinatura esta fora do escopo" in out["error_message"]
    assert cap["pending"] is None


async def test_ja_no_status_sem_token(monkeypatch: pytest.MonkeyPatch) -> None:
    cap = _wire(monkeypatch, [("KEYWORD", "PAUSED")])
    out = await _chamar("KEYWORD", "PAUSED")
    assert out["status"] == "no_changes"
    assert "ja esta PAUSED" in out["message"]
    assert "confirmation_token" not in out
    assert cap["pending"] is None


async def test_mais_de_uma_linha_do_tipo_recusa(monkeypatch: pytest.MonkeyPatch) -> None:
    cap = _wire(monkeypatch, [("KEYWORD", "PAUSED"), ("KEYWORD", "ENABLED")])
    out = await _chamar("KEYWORD", "ENABLED")
    assert out["status"] == "error"
    assert "F185" in out["error_message"]
    assert cap["pending"] is None


# --------------------------------------------------------------------------- #
# Dry-run: preview com token
# --------------------------------------------------------------------------- #
async def test_enabled_aviso_e_risco(monkeypatch: pytest.MonkeyPatch) -> None:
    cap = _wire(monkeypatch, [("KEYWORD", "PAUSED")])
    out = await _chamar("KEYWORD", "ENABLED")
    assert out["status"] == "dry_run"
    assert out["confirmation_token"] == "TOKEN123"
    assert "aplicar recomendacoes deste tipo sozinho" in out["blast_summary"]
    assert "aplicar recomendacoes deste tipo sozinho" in out["aviso"]
    assert "liga aplicacao automatica do Google" in out["confirmation_reason"]
    assert out["status_antes"] == "PAUSED" and out["status_depois"] == "ENABLED"
    pend = cap["pending"]
    assert pend["operation_type"] == "update_recommendation_subscription"
    assert pend["payload"] == {
        "type": "KEYWORD",
        "status": "ENABLED",
        "status_antes": "PAUSED",
        "__target_count__": 1,
        "__partial_failure__": True,
        "__params_summary__": {"type": "KEYWORD", "status": "ENABLED"},
    }
    # O status lido veio do proto, nao de um default: o SELECT tem que pedi-lo.
    assert cap["queries"] == [assinatura_query("KEYWORD")]


async def test_pausar_emite_token_sem_aviso(monkeypatch: pytest.MonkeyPatch) -> None:
    cap = _wire(monkeypatch, [("RESPONSIVE_SEARCH_AD", "ENABLED")])
    out = await _chamar("RESPONSIVE_SEARCH_AD", "PAUSED")
    assert out["status"] == "dry_run"
    assert out["aviso"] is None
    assert "ENABLED -> PAUSED" in out["blast_summary"]
    assert cap["pending"]["payload"]["status_antes"] == "ENABLED"


def test_query_e_a_do_contrato() -> None:
    assert assinatura_query("RESPONSIVE_SEARCH_AD") == (
        "SELECT recommendation_subscription.type, recommendation_subscription.status, "
        "recommendation_subscription.modify_date_time FROM recommendation_subscription "
        "WHERE recommendation_subscription.type = 'RESPONSIVE_SEARCH_AD'"
    )
    with pytest.raises(ValueError):
        assinatura_query("X' OR 1=1 --")
    with pytest.raises(ValueError):
        assinatura_query("UNKNOWN")


# --------------------------------------------------------------------------- #
# Blast radius
# --------------------------------------------------------------------------- #
def test_blast_radius_enabled_confirma_com_motivo() -> None:
    r = classify(
        operation="update_recommendation_subscription",
        params={"target_count": 1, "status": "ENABLED"},
    )
    assert r.level is RiskLevel.CONFIRM
    assert "liga aplicacao automatica do Google" in r.reason


def test_blast_radius_paused_confirma() -> None:
    r = classify(
        operation="update_recommendation_subscription",
        params={"target_count": 1, "status": "PAUSED"},
    )
    assert r.level is RiskLevel.CONFIRM
    assert "unknown operation" not in r.reason


# --------------------------------------------------------------------------- #
# Builder
# --------------------------------------------------------------------------- #
def test_builder_registrado() -> None:
    from src.google_ads.mutates._common import get_builder, import_all_builders

    import_all_builders()
    assert (
        get_builder("update_recommendation_subscription")
        is build_update_recommendation_subscription
    )


def test_builder_monta_update_de_status() -> None:
    client = make_capture_client()
    ops = build_update_recommendation_subscription(
        client, _CID, {"type": "RESPONSIVE_SEARCH_AD", "status": "PAUSED"}
    )
    assert len(ops) == 1
    assert ops[0].field("recommendation_subscription_operation.update.resource_name") == (
        f"customers/{_CID}/recommendationSubscriptions/RESPONSIVE_SEARCH_AD"
    )
    assert ops[0].field("recommendation_subscription_operation.update.status") == "PAUSED"
    assert ops[0].has("recommendation_subscription_operation.create") is False
    assert list(client.copy_from.call_args_list[0].args[1].paths) == ["status"]


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "UNKNOWN", "status": "PAUSED"},
        {"type": "RESPONSIVE_SEARCH_AD", "status": "REMOVED"},
    ],
)
def test_builder_recusa_fora_do_contrato(payload: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        build_update_recommendation_subscription(make_capture_client(), _CID, payload)


def test_mutate_operation_do_sdk_tem_o_campo() -> None:
    """Probe do SDK instalado: o oneof existe e o update aceita status + mask."""
    from google.ads.googleads.v25.services.types.google_ads_service import MutateOperation

    op = MutateOperation()
    op.recommendation_subscription_operation.update.resource_name = (
        f"customers/{_CID}/recommendationSubscriptions/RESPONSIVE_SEARCH_AD"
    )
    op.recommendation_subscription_operation.update.status = (
        RecommendationSubscriptionStatusEnum.RecommendationSubscriptionStatus.PAUSED
    )
    assert MutateOperation.pb(op).WhichOneof("operation") == "recommendation_subscription_operation"
