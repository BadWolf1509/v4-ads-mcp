"""Pacing Meta: calculo puro (pacing.py) e fluxo da tool (calendario, orcamento, truncamento)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current
from src.mcp.tools import meta_get_budget_pacing as modulo
from src.meta_ads.pacing import orcamento_total, projetar, ritmo_de

_CONTA = "act_1"


def test_dia_corrente_nao_conta_como_dia_inteiro():
    # dia 11 com 1000 gastos em 10 dias fechados: media 100, nao 90,9 (F199)
    r = projetar(gasto_fechado=1000.0, dias_fechados=10, dias_no_mes=30)
    assert r["media_diaria"] == 100.0
    assert r["projecao"] == 3000.0


def test_dia_1_sem_dia_fechado_nao_projeta():
    r = projetar(gasto_fechado=None, dias_fechados=0, dias_no_mes=30)
    assert r == {"media_diaria": None, "projecao": None}


def test_orcamento_de_campanha_nao_soma_com_conjunto():
    assert orcamento_total(campanha=500.0, conjuntos=[None, None]) == 500.0


def test_conjunto_sem_orcamento_legivel_e_null():
    assert orcamento_total(campanha=None, conjuntos=[100.0, None]) is None


def test_sem_conjunto_e_sem_campanha_e_null():
    assert orcamento_total(campanha=None, conjuntos=[]) is None


def test_soma_dos_conjuntos():
    assert orcamento_total(campanha=None, conjuntos=[100.0, 50.5]) == 150.5


def test_orcamento_vitalicio_nao_entra_em_projecao_mensal():
    r = ritmo_de(lifetime_budget=1000.0, daily_budget=None)
    assert r["projecao"] is None
    assert r["tipo_orcamento"] == "vitalicio"
    assert "vital" in r["observacao"]


def test_ritmo_diario_calcula_percentuais():
    r = ritmo_de(
        daily_budget=100.0,
        lifetime_budget=None,
        gasto_fechado=1000.0,
        dias_fechados=10,
        dias_no_mes=30,
    )
    assert r["orcamento_mensal_brl"] == 3000.0
    assert r["projecao"] == 3000.0
    assert r["gasto_pct_do_orcamento_mensal"] == 33.3
    assert r["projecao_vs_orcamento_pct"] == 100.0


def test_sem_orcamento_nao_tem_percentual():
    r = ritmo_de(
        daily_budget=None,
        lifetime_budget=None,
        gasto_fechado=1000.0,
        dias_fechados=10,
        dias_no_mes=30,
    )
    assert r["tipo_orcamento"] is None
    assert r["orcamento_mensal_brl"] is None
    assert r["projecao_vs_orcamento_pct"] is None
    assert r["projecao"] == 3000.0  # o gasto projeta mesmo sem orcamento


# ---------- fluxo da tool ----------


@pytest.fixture(autouse=True)
def _ctx() -> Iterator[None]:
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _camp(i: str, daily: float | None = None, lifetime: float | None = None) -> dict[str, Any]:
    return {
        "id": i,
        "name": f"C{i}",
        "daily_budget_brl": daily,
        "lifetime_budget_brl": lifetime,
    }


def _adset(
    i: str, camp: str, daily: float | None = None, lifetime: float | None = None
) -> dict[str, Any]:
    return {
        "id": i,
        "name": f"A{i}",
        "campaign_id": camp,
        "daily_budget_brl": daily,
        "lifetime_budget_brl": lifetime,
    }


def _insight(camp: str, spend: str | None) -> dict[str, Any]:
    linha: dict[str, Any] = {"campaign_id": camp, "campaign_name": f"C{camp}"}
    if spend is not None:
        linha["spend"] = spend
    return linha


async def _roda(
    *,
    hoje: date,
    campanhas: list[dict[str, Any]],
    conjuntos: list[dict[str, Any]],
    insights: dict[str, Any] | None,
    trunc_camp: bool = False,
    trunc_adset: bool = False,
    moeda: str = "BRL",
) -> tuple[dict[str, Any], AsyncMock]:
    g = AsyncMock(side_effect=[{"currency": moeda}, insights or {"data": []}])

    async def listar(
        ctx: Any, act: str, level: str, status: str | None, limit: int
    ) -> tuple[list[dict[str, Any]], bool]:
        assert status == "ACTIVE"
        if level == "campaign":
            return campanhas, trunc_camp
        return conjuntos, trunc_adset

    with (
        patch.object(modulo, "run_meta_graph_get", g),
        patch.object(modulo, "listar_entidades", AsyncMock(side_effect=listar)),
        patch.object(modulo, "resolve_meta_account_today", AsyncMock(return_value=hoje)),
    ):
        r = await modulo.meta_get_budget_pacing({"ad_account_id": _CONTA})
    return r, g


@pytest.mark.asyncio
async def test_projeta_pelos_dias_fechados_e_exclui_hoje() -> None:
    r, g = await _roda(
        hoje=date(2026, 10, 11),
        campanhas=[_camp("1", daily=100.0)],
        conjuntos=[],
        insights={"data": [_insight("1", "1000.00")]},
    )
    assert r["status"] == "success"
    ins = g.await_args_list[1].kwargs
    assert ins["edge"] == "/act_1/insights"
    assert '"since":"2026-10-01"' in ins["params"]["time_range"]
    assert '"until":"2026-10-10"' in ins["params"]["time_range"]
    c = r["campaigns"][0]
    assert c["gasto_fechado_brl"] == 1000.0
    assert c["media_diaria_brl"] == 100.0
    assert c["projecao_mensal_brl"] == 3100.0  # 100 * 31 dias de outubro
    assert c["orcamento_mensal_brl"] == 3100.0
    assert r["dias_fechados"] == 10
    assert r["date_range"] == {"from": "2026-10-01", "to": "2026-10-10"}
    assert r["inclui_dia_corrente"] is False
    assert "ativ" in r["escopo"].lower()


@pytest.mark.asyncio
async def test_dia_1_nao_chama_insights_e_projecao_e_null() -> None:
    r, g = await _roda(
        hoje=date(2026, 10, 1),
        campanhas=[_camp("1", daily=100.0)],
        conjuntos=[],
        insights=None,
    )
    assert g.await_count == 1  # so a moeda
    c = r["campaigns"][0]
    assert c["gasto_fechado_brl"] is None
    assert c["media_diaria_brl"] is None and c["projecao_mensal_brl"] is None
    assert r["date_range"] is None
    assert r["dias_fechados"] == 0


@pytest.mark.asyncio
async def test_campanha_com_orcamento_proprio_nao_soma_conjuntos() -> None:
    r, _ = await _roda(
        hoje=date(2026, 10, 11),
        campanhas=[_camp("1", daily=500.0)],
        conjuntos=[_adset("a", "1", daily=300.0), _adset("b", "1", daily=300.0)],
        insights={"data": [_insight("1", "10.00")]},
    )
    assert r["campaigns"][0]["orcamento_diario_brl"] == 500.0
    assert r["campaigns"][0]["orcamento_em"] == "campanha"


@pytest.mark.asyncio
async def test_orcamento_nos_conjuntos_soma_e_um_ilegivel_zera_o_total() -> None:
    r, _ = await _roda(
        hoje=date(2026, 10, 11),
        campanhas=[_camp("1"), _camp("2")],
        conjuntos=[
            _adset("a", "1", daily=100.0),
            _adset("b", "1", daily=50.0),
            _adset("c", "2", daily=100.0),
            _adset("d", "2"),
        ],
        insights={"data": [_insight("1", "10.00"), _insight("2", "10.00")]},
    )
    por_id = {c["campaign_id"]: c for c in r["campaigns"]}
    assert por_id["1"]["orcamento_diario_brl"] == 150.0
    assert por_id["1"]["orcamento_em"] == "conjuntos"
    assert por_id["2"]["orcamento_diario_brl"] is None
    assert por_id["2"]["projecao_vs_orcamento_pct"] is None
    assert r["total"]["orcamento_diario_brl"] is None


@pytest.mark.asyncio
async def test_vitalicio_nao_projeta_e_avisa_na_linha() -> None:
    r, _ = await _roda(
        hoje=date(2026, 10, 11),
        campanhas=[_camp("1", lifetime=1000.0)],
        conjuntos=[],
        insights={"data": [_insight("1", "100.00")]},
    )
    c = r["campaigns"][0]
    assert c["tipo_orcamento"] == "vitalicio"
    assert c["projecao_mensal_brl"] is None
    assert "vital" in c["observacao"]


@pytest.mark.asyncio
async def test_vitalicio_nos_conjuntos_nao_projeta() -> None:
    r, _ = await _roda(
        hoje=date(2026, 10, 11),
        campanhas=[_camp("1")],
        conjuntos=[_adset("a", "1", lifetime=500.0), _adset("b", "1", daily=10.0)],
        insights={"data": [_insight("1", "100.00")]},
    )
    c = r["campaigns"][0]
    assert c["tipo_orcamento"] == "vitalicio"
    assert c["projecao_mensal_brl"] is None
    assert r["total"]["projecao_mensal_brl"] is None


@pytest.mark.asyncio
async def test_campanha_ativa_sem_linha_de_insights_gastou_zero() -> None:
    r, _ = await _roda(
        hoje=date(2026, 10, 11),
        campanhas=[_camp("1", daily=100.0)],
        conjuntos=[],
        insights={"data": []},
    )
    assert r["campaigns"][0]["gasto_fechado_brl"] == 0.0
    assert r["campaigns"][0]["projecao_mensal_brl"] == 0.0


@pytest.mark.asyncio
async def test_spend_nao_reportado_na_linha_e_null_nao_zero() -> None:
    r, _ = await _roda(
        hoje=date(2026, 10, 11),
        campanhas=[_camp("1", daily=100.0)],
        conjuntos=[],
        insights={"data": [_insight("1", None)]},
    )
    c = r["campaigns"][0]
    assert c["gasto_fechado_brl"] is None
    assert c["projecao_mensal_brl"] is None


@pytest.mark.asyncio
async def test_truncamento_de_campanhas_anula_o_total() -> None:
    r, _ = await _roda(
        hoje=date(2026, 10, 11),
        campanhas=[_camp("1", daily=100.0)],
        conjuntos=[],
        insights={"data": [_insight("1", "1000.00")]},
        trunc_camp=True,
    )
    assert r["truncated"] is True
    assert r["total"]["projecao_mensal_brl"] is None
    assert r["total"]["orcamento_diario_brl"] is None
    assert r["total"]["gasto_fechado_brl"] is None


@pytest.mark.asyncio
async def test_truncamento_de_conjuntos_anula_orcamento_de_quem_depende_deles() -> None:
    r, _ = await _roda(
        hoje=date(2026, 10, 11),
        campanhas=[_camp("1"), _camp("2", daily=100.0)],
        conjuntos=[_adset("a", "1", daily=100.0)],
        insights={"data": [_insight("1", "10.00"), _insight("2", "10.00")]},
        trunc_adset=True,
    )
    por_id = {c["campaign_id"]: c for c in r["campaigns"]}
    assert r["truncated"] is True
    assert por_id["1"]["orcamento_diario_brl"] is None
    assert por_id["2"]["orcamento_diario_brl"] == 100.0
    assert r["total"]["orcamento_diario_brl"] is None


@pytest.mark.asyncio
async def test_insights_com_proxima_pagina_marca_truncated_e_gasto_null_de_quem_falta() -> None:
    r, _ = await _roda(
        hoje=date(2026, 10, 11),
        campanhas=[_camp("1", daily=100.0), _camp("2", daily=100.0)],
        conjuntos=[],
        insights={"data": [_insight("1", "10.00")], "paging": {"next": "https://x"}},
    )
    por_id = {c["campaign_id"]: c for c in r["campaigns"]}
    assert r["truncated"] is True
    assert por_id["1"]["gasto_fechado_brl"] == 10.0
    assert por_id["2"]["gasto_fechado_brl"] is None  # ausente nao e prova de zero
    assert r["total"]["projecao_mensal_brl"] is None


@pytest.mark.asyncio
async def test_total_soma_quando_tudo_legivel() -> None:
    r, _ = await _roda(
        hoje=date(2026, 10, 11),
        campanhas=[_camp("1", daily=100.0), _camp("2", daily=50.0)],
        conjuntos=[],
        insights={"data": [_insight("1", "1000.00"), _insight("2", "500.00")]},
    )
    t = r["total"]
    assert t["gasto_fechado_brl"] == 1500.0
    assert t["orcamento_diario_brl"] == 150.0
    assert t["projecao_mensal_brl"] == 4650.0


@pytest.mark.asyncio
async def test_moeda_diferente_de_brl_e_erro() -> None:
    r, g = await _roda(
        hoje=date(2026, 10, 11), campanhas=[], conjuntos=[], insights=None, moeda="USD"
    )
    assert r["status"] == "error"
    assert "USD" in r["error_message"]
    assert g.await_count == 1


@pytest.mark.asyncio
async def test_falha_da_graph_vira_erro() -> None:
    g = AsyncMock(side_effect=RuntimeError("boom"))
    with (
        patch.object(modulo, "run_meta_graph_get", g),
        patch.object(
            modulo, "resolve_meta_account_today", AsyncMock(return_value=date(2026, 10, 11))
        ),
    ):
        r = await modulo.meta_get_budget_pacing({"ad_account_id": _CONTA})
    assert r["status"] == "error"
