"""apply_change de create_rsa/update_rsa: o pos-check relê a politica do anuncio (M1).

O estado devolvido e FOTO do instante, nao veredito; a releitura quebrada nao pode
transformar sucesso de escrita em erro (F83/F91)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from src.google_ads.queries.rsa_estado import parse_rsa_estado_row
from src.mcp.tools import apply_change as mod
from tests.unit.fixtures.fake_pool import FakePool


@pytest.fixture(autouse=True)
def _ctx():
    from src.mcp.context import McpRequestContext, clear_current, set_current

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _saved(op: str = "update_rsa") -> SimpleNamespace:
    return SimpleNamespace(
        operation_type=op,
        customer_id="1234567890",
        blast_summary="x",
        payload={"__target_count__": 1, "__partial_failure__": True},
    )


def _mutacao(nomes: list[str], efeitos: list[str | None] | None = None) -> dict[str, Any]:
    efeitos = efeitos or ["mudou"] * len(nomes)
    return {
        "provider_request_id": "req-1",
        "applied_count": len(nomes),
        "changed_count": len(nomes),
        "resource_names": nomes,
        "partial_failures": [
            {"index": i, "status": "success", "efeito": e} for i, e in enumerate(efeitos)
        ],
    }


def _estado(ad_id: str, review: str = "REVIEW_IN_PROGRESS", aprov: str | None = None) -> dict:
    return {
        "ad_id": ad_id,
        "approval_status": aprov,
        "review_status": review,
        "topicos": [],
        "assets_reprovados": [],
        "pinos": {},
    }


def _wire(monkeypatch, *, saved, mutacao, rows=None, explode: bool = False) -> list[str]:
    queries: list[str] = []

    async def _consume(conn, *, token, session_id):
        return saved

    async def _run_mutation(**kwargs: Any):
        return mutacao

    async def _run_report(**kwargs: Any):
        queries.append(kwargs["query"])
        assert kwargs["row_formatter"] is parse_rsa_estado_row
        if explode:
            raise RuntimeError("boom")
        return rows if rows is not None else []

    monkeypatch.setattr(mod, "consume", _consume)
    monkeypatch.setattr(mod, "run_mutation", _run_mutation)
    monkeypatch.setattr(mod, "run_report", _run_report)
    monkeypatch.setattr(mod.connection, "get_pool", lambda: FakePool())
    return queries


@pytest.mark.asyncio
async def test_update_rsa_devolve_estado_revisao(monkeypatch) -> None:
    queries = _wire(
        monkeypatch,
        saved=_saved(),
        mutacao=_mutacao(["customers/1234567890/ads/99"]),
        rows=[_estado("99")],
    )
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["status"] == "applied" and out["applied_count"] == 1
    assert out["estado_revisao"][0]["review_status"] == "REVIEW_IN_PROGRESS"
    assert out["estado_revisao"][0]["approval_status"] is None
    assert "lido_em" in out
    assert "não é veredito" in out["aviso_revisao"]
    assert out["releitura"]["tool"] == "run_gaql"
    assert out["releitura"]["query"] == queries[0]
    assert "segments.date" not in queries[0]
    assert out["confirmation_error"] is None
    # O que o _Padrao devolve segue la.
    assert out["resource_names"] == ["customers/1234567890/ads/99"]
    assert out["partial_failure"] is True


@pytest.mark.asyncio
async def test_create_rsa_extrai_ad_id_de_adgroupad(monkeypatch) -> None:
    queries = _wire(
        monkeypatch,
        saved=_saved("create_rsa"),
        mutacao=_mutacao(["customers/1234567890/adGroupAds/5~77"]),
        rows=[_estado("77")],
    )
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert "IN (77)" in queries[0]
    assert out["estado_revisao"][0]["ad_id"] == "77"


@pytest.mark.asyncio
async def test_releitura_que_quebra_preserva_sucesso(monkeypatch) -> None:
    _wire(
        monkeypatch,
        saved=_saved(),
        mutacao=_mutacao(["customers/1234567890/ads/99"]),
        explode=True,
    )
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["status"] == "applied" and out["provider_request_id"] == "req-1"
    assert out["estado_revisao"] is None
    assert out["lido_em"] is None
    assert "run_gaql" in out["confirmation_error"]


@pytest.mark.asyncio
async def test_ad_ausente_na_releitura(monkeypatch) -> None:
    _wire(
        monkeypatch,
        saved=_saved(),
        mutacao=_mutacao(["customers/1234567890/ads/1", "customers/1234567890/ads/2"]),
        rows=[_estado("1")],
    )
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    por_id = {e["ad_id"]: e for e in out["estado_revisao"]}
    assert por_id["1"]["review_status"] == "REVIEW_IN_PROGRESS"
    assert por_id["2"]["approval_status"] is None
    assert por_id["2"]["motivo"] == "nao_encontrado_na_releitura"


@pytest.mark.asyncio
async def test_so_rele_o_que_mudou(monkeypatch) -> None:
    # sem_efeito COM resource_name e estado sintetico (o executor real nao produz isso):
    # serve so para provar que o filtro por efeito corta a linha.
    queries = _wire(
        monkeypatch,
        saved=_saved(),
        mutacao=_mutacao(
            ["customers/1234567890/ads/1", "", "customers/1234567890/ads/3"],
            ["mudou", None, "sem_efeito"],
        ),
        rows=[_estado("1")],
    )
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert "IN (1)" in queries[0]
    assert [e["ad_id"] for e in out["estado_revisao"]] == ["1"]


@pytest.mark.asyncio
async def test_nada_gravado_nao_consulta(monkeypatch) -> None:
    queries = _wire(
        monkeypatch,
        saved=_saved(),
        mutacao=_mutacao([""], [None]),
    )
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert queries == []
    assert out["estado_revisao"] == [] and out["releitura"] is None


@pytest.mark.asyncio
async def test_resource_name_irreconhecido_nao_derruba_o_lote(monkeypatch) -> None:
    _wire(
        monkeypatch,
        saved=_saved(),
        mutacao=_mutacao(["customers/1234567890/ads/1", "lixo"]),
        rows=[_estado("1")],
    )
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["status"] == "applied" and out["confirmation_error"] is None
    assert out["estado_revisao"][0]["ad_id"] == "1"
    ruim = out["estado_revisao"][1]
    assert ruim["ad_id"] is None and ruim["resource_name"] == "lixo"
    assert ruim["approval_status"] is None
    assert ruim["motivo"] == "resource_name_irreconhecido"
    assert out["lido_em"] is not None


@pytest.mark.asyncio
async def test_so_irreconhecido_nao_aponta_releitura_inexistente(monkeypatch) -> None:
    queries = _wire(monkeypatch, saved=_saved(), mutacao=_mutacao(["lixo"]))
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert queries == [] and out["releitura"] is None and out["lido_em"] is None
    assert out["estado_revisao"][0]["motivo"] == "resource_name_irreconhecido"


@pytest.mark.asyncio
async def test_nada_gravado_tem_lido_em_none(monkeypatch) -> None:
    _wire(monkeypatch, saved=_saved(), mutacao=_mutacao([""], [None]))
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["lido_em"] is None
