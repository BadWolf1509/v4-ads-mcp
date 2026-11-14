"""apply_change de update_recommendation_subscription: o pos-check relê o status (N3).

O Google aceita operacao e pode nao executa-la (F184): a releitura e quem diz se a
assinatura ficou no status pedido. Divergencia vira `efeito: sem_efeito`; releitura
quebrada nao transforma sucesso de escrita em erro (F83/F91).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from src.google_ads.queries.recommendation_subscription import (
    assinatura_query,
    parse_assinatura_row,
)
from src.mcp.tools import apply_change as mod
from tests.unit.fixtures.fake_pool import FakePool
from tests.unit.test_update_recommendation_subscription import linha_de_assinatura

_CID = "7862230676"
_RN = f"customers/{_CID}/recommendationSubscriptions/RESPONSIVE_SEARCH_AD"


@pytest.fixture(autouse=True)
def _ctx():
    from src.mcp.context import McpRequestContext, clear_current, set_current

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _saved(status: str = "PAUSED") -> SimpleNamespace:
    return SimpleNamespace(
        operation_type="update_recommendation_subscription",
        customer_id=_CID,
        blast_summary="x",
        payload={
            "type": "RESPONSIVE_SEARCH_AD",
            "status": status,
            "status_antes": "ENABLED" if status == "PAUSED" else "PAUSED",
            "__target_count__": 1,
            "__partial_failure__": True,
            "__params_summary__": {"type": "RESPONSIVE_SEARCH_AD", "status": status},
        },
    )


def _mutacao() -> dict[str, Any]:
    return {
        "provider_request_id": "req-1",
        "applied_count": 1,
        "changed_count": 1,
        "resource_names": [_RN],
        "partial_failures": [{"index": 0, "status": "success", "error": None, "efeito": "mudou"}],
        "motivos_medidos": True,
    }


def _wire(
    monkeypatch,
    *,
    saved,
    releitura: list[str] | None = None,
    explode: bool = False,
) -> dict[str, Any]:
    cap: dict[str, Any] = {"queries": [], "mutou": False}

    async def _consume(conn, *, token, session_id):
        return saved

    async def _run_mutation(**kwargs: Any):
        cap["mutou"] = True
        cap["mutation_kwargs"] = kwargs
        return _mutacao()

    async def _run_report(**kwargs: Any):
        cap["queries"].append(kwargs["query"])
        cap["operation_name"] = kwargs["operation_name"]
        assert kwargs["row_formatter"] is parse_assinatura_row
        if explode:
            raise RuntimeError("boom")
        fmt = kwargs["row_formatter"]
        return [
            fmt(linha_de_assinatura(kwargs["query"], "RESPONSIVE_SEARCH_AD", s))
            for s in (releitura or [])
        ]

    monkeypatch.setattr(mod, "consume", _consume)
    monkeypatch.setattr(mod, "run_mutation", _run_mutation)
    monkeypatch.setattr(mod, "run_report", _run_report)
    monkeypatch.setattr(mod.connection, "get_pool", lambda: FakePool())
    return cap


@pytest.mark.asyncio
async def test_status_resultante(monkeypatch) -> None:
    cap = _wire(monkeypatch, saved=_saved("PAUSED"), releitura=["PAUSED"])
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["status"] == "applied" and out["applied_count"] == 1
    assert out["status_resultante"] == "PAUSED"
    assert out["status_pedido"] == "PAUSED"
    assert out["status_antes"] == "ENABLED"
    assert out["motivo_status_resultante"] is None
    assert out["confirmation_error"] is None
    assert out["partial_failures"][0]["efeito"] == "mudou"
    assert out["changed_count"] == 1
    assert out["partial_failure"] is True
    assert cap["queries"] == [assinatura_query("RESPONSIVE_SEARCH_AD")]
    assert cap["mutation_kwargs"]["partial_failure"] is True
    assert cap["mutation_kwargs"]["params_summary"] == {
        "type": "RESPONSIVE_SEARCH_AD",
        "status": "PAUSED",
    }


@pytest.mark.asyncio
async def test_divergencia_vira_sem_efeito(monkeypatch) -> None:
    _wire(monkeypatch, saved=_saved("PAUSED"), releitura=["ENABLED"])
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["status"] == "applied"
    assert out["status_resultante"] == "ENABLED"
    assert out["partial_failures"][0]["efeito"] == "sem_efeito"
    assert out["changed_count"] == 0
    # o veredito do Google segue o que o Google disse
    assert out["partial_failures"][0]["status"] == "success"
    assert out["motivo_status_resultante"] is not None


@pytest.mark.asyncio
async def test_releitura_falha_preserva_sucesso(monkeypatch) -> None:
    _wire(monkeypatch, saved=_saved("PAUSED"), explode=True)
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["status"] == "applied" and out["provider_request_id"] == "req-1"
    assert out["status_resultante"] is None
    assert "RuntimeError" in out["confirmation_error"]
    # sem releitura, o efeito nao e rebaixado: nao saber nao e sem_efeito
    assert out["partial_failures"][0]["efeito"] == "mudou"


@pytest.mark.asyncio
async def test_assinatura_sumiu_na_releitura(monkeypatch) -> None:
    _wire(monkeypatch, saved=_saved("PAUSED"), releitura=[])
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["status"] == "applied"
    assert out["status_resultante"] is None
    assert out["motivo_status_resultante"] == "assinatura_nao_encontrada_na_releitura"
    assert out["confirmation_error"] is None
    assert out["partial_failures"][0]["efeito"] == "mudou"


@pytest.mark.asyncio
async def test_releitura_ambigua(monkeypatch) -> None:
    _wire(monkeypatch, saved=_saved("PAUSED"), releitura=["PAUSED", "ENABLED"])
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["status_resultante"] is None
    assert out["motivo_status_resultante"] == "mais_de_uma_linha_do_tipo"


@pytest.mark.asyncio
async def test_payload_sem_chave_levanta_antes_da_escrita(monkeypatch) -> None:
    saved = _saved("PAUSED")
    del saved.payload["status"]
    cap = _wire(monkeypatch, saved=saved, releitura=["PAUSED"])
    with pytest.raises(KeyError):
        await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert cap["mutou"] is False
