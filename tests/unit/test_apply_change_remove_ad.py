"""apply_change de remove_ad (S3): o pos-check rele o status de cada anuncio.

O Google aceita operacao e pode nao executa-la (F184): a releitura diz se o anuncio
ficou REMOVED. O veredito vai em `conferencia` na linha; `efeito` e `changed_count`
seguem o ACK do Google (decisao "Campo proprio"). Releitura quebrada nao transforma
sucesso de escrita em erro (F83/F91).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from src.google_ads.queries.remover_anuncio import anuncios_query, parse_anuncio_row
from src.governance.blast_radius import RiskLevel, classify
from src.mcp.tools import apply_change as mod
from tests.unit.fixtures.fake_pool import FakePool
from tests.unit.test_remove_ad import linha_de_anuncio

_CID = "7862230676"
_DIVERGE = (
    "releitura diverge do pedido: possivel operacao aceita sem executar (F184), leitura "
    "defasada ou mudanca concorrente"
)


class _Log:
    def __init__(self) -> None:
        self.eventos: list[tuple[str, dict[str, Any]]] = []

    def warning(self, evento: str, **kw: Any) -> None:
        self.eventos.append((evento, kw))


@pytest.fixture(autouse=True)
def _ctx():
    from src.mcp.context import McpRequestContext, clear_current, set_current

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _saved() -> SimpleNamespace:
    return SimpleNamespace(
        operation_type="remove_ad",
        customer_id=_CID,
        blast_summary="x",
        payload={
            "ads": [{"ad_group_id": "100", "ad_id": "11"}],
            "__target_count__": 1,
            "__partial_failure__": True,
            "__params_summary__": {"count": 1, "ad_ids": ["11"]},
        },
    )


def _mutacao() -> dict[str, Any]:
    return {
        "provider_request_id": "req-1",
        "applied_count": 1,
        "changed_count": 1,
        "resource_names": [f"customers/{_CID}/adGroupAds/100~11"],
        "partial_failures": [{"index": 0, "status": "success", "error": None, "efeito": "mudou"}],
        "motivos_medidos": True,
    }


def _wire(
    monkeypatch,
    *,
    saved,
    releitura: list[str | None] | None = None,
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
        assert kwargs["row_formatter"] is parse_anuncio_row
        if explode:
            raise RuntimeError("boom")
        fmt = kwargs["row_formatter"]
        return [
            fmt(linha_de_anuncio(kwargs["query"], ad_id="11", ad_group_id="100", status=s))
            for s in (releitura or [])
        ]

    monkeypatch.setattr(mod, "consume", _consume)
    monkeypatch.setattr(mod, "run_mutation", _run_mutation)
    monkeypatch.setattr(mod, "run_report", _run_report)
    monkeypatch.setattr(mod.connection, "get_pool", lambda: FakePool())
    return cap


@pytest.mark.asyncio
async def test_releitura_removed_confere(monkeypatch) -> None:
    cap = _wire(monkeypatch, saved=_saved(), releitura=["REMOVED"])
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["status"] == "applied" and out["applied_count"] == 1
    linha = out["partial_failures"][0]
    assert linha["efeito"] == "mudou"
    assert linha["conferencia"] == {
        "campo": "status",
        "pedido": "REMOVED",
        "relido": "REMOVED",
        "motivo": "confere",
    }
    assert out["confirmation_error"] is None
    assert cap["queries"] == [anuncios_query(["11"])]
    assert cap["mutation_kwargs"]["partial_failure"] is True
    assert cap["mutation_kwargs"]["params_summary"] == {"count": 1, "ad_ids": ["11"]}


@pytest.mark.asyncio
async def test_releitura_enabled_diverge_sem_rebaixar_o_ack(monkeypatch) -> None:
    log = _Log()
    monkeypatch.setattr(mod, "log", log)
    _wire(monkeypatch, saved=_saved(), releitura=["ENABLED"])
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["status"] == "applied"
    linha = out["partial_failures"][0]
    # efeito e changed_count sao o ACK do Google e batem com o audit
    assert linha["efeito"] == "mudou"
    assert out["changed_count"] == 1
    assert linha["status"] == "success"
    assert linha["conferencia"] == {
        "campo": "status",
        "pedido": "REMOVED",
        "relido": "ENABLED",
        "motivo": _DIVERGE,
    }
    assert log.eventos == [
        (
            "conferencia_pos_write_divergiu",
            {"operation_type": "remove_ad", "customer_id": _CID, "campo": "status"},
        )
    ]


@pytest.mark.asyncio
async def test_releitura_sem_a_linha_nao_confere(monkeypatch) -> None:
    _wire(monkeypatch, saved=_saved(), releitura=[])
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["status"] == "applied"
    assert out["partial_failures"][0]["efeito"] == "mudou"
    assert out["partial_failures"][0]["conferencia"] is None
    assert out["confirmation_error"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("relido", [None, "UNKNOWN"])
async def test_status_nao_lido_nao_confere(monkeypatch, relido) -> None:
    _wire(monkeypatch, saved=_saved(), releitura=[relido])
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["status"] == "applied"
    assert out["partial_failures"][0]["conferencia"] is None
    assert out["changed_count"] == 1


@pytest.mark.asyncio
async def test_releitura_que_levanta_preserva_sucesso(monkeypatch) -> None:
    _wire(monkeypatch, saved=_saved(), explode=True)
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["status"] == "applied" and out["provider_request_id"] == "req-1"
    assert "RuntimeError" in out["confirmation_error"]
    assert out["partial_failures"][0]["efeito"] == "mudou"
    assert out["partial_failures"][0]["conferencia"] is None


@pytest.mark.asyncio
async def test_payload_ruim_levanta_antes_da_escrita(monkeypatch) -> None:
    saved = _saved()
    saved.payload["ads"] = [{"ad_group_id": "100", "ad_id": "11 OR 1=1"}]
    cap = _wire(monkeypatch, saved=saved, releitura=["REMOVED"])
    with pytest.raises(ValueError):
        await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert cap["mutou"] is False


def test_classify_confirm_fixo() -> None:
    assert classify(operation="remove_ad", params={"target_count": 1}).level == RiskLevel.CONFIRM
    for n in (0, 1, 5, 20, 100):
        r = classify(operation="remove_ad", params={"target_count": n})
        assert r.level is RiskLevel.CONFIRM
        assert "irreversivel" in r.reason
        assert "unknown operation" not in r.reason
