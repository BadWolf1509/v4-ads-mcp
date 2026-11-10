"""Pacing Meta: calculo puro (pacing.py) e fluxo da tool (calendario, orcamento, truncamento)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack
from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
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


def test_vitalicio_em_conjunto_marca_a_flag_em_orcamento_da_campanha() -> None:
    orc = modulo._orcamento_da_campanha(
        {"id": "1"},
        [
            {"id": "a", "daily_budget_brl": 50.0, "lifetime_budget_brl": None},
            {"id": "b", "daily_budget_brl": None, "lifetime_budget_brl": 500.0},
        ],
        conjuntos_truncados=False,
    )
    assert orc["vitalicio_em_conjuntos"] is True
    assert orc["diario"] is None and orc["vitalicio"] is None


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
        "effective_status": "ACTIVE",
        "daily_budget_brl": daily,
        "lifetime_budget_brl": lifetime,
    }


def _adset(
    i: str, camp: str, daily: float | None = None, lifetime: float | None = None
) -> dict[str, Any]:
    return {
        "id": i,
        "name": f"A{i}",
        "effective_status": "ACTIVE",
        "campaign_id": camp,
        "daily_budget_brl": daily,
        "lifetime_budget_brl": lifetime,
    }


def _insight(camp: str, spend: str | None) -> dict[str, Any]:
    linha: dict[str, Any] = {"campaign_id": camp, "campaign_name": f"C{camp}"}
    if spend is not None:
        linha["spend"] = spend
    return linha


class _ConnComMoeda:
    """Conexao falsa: devolve a moeda da linha de `meta_ad_accounts` (None = sem linha)."""

    def __init__(self, moeda_na_tabela: str | None) -> None:
        self._moeda = moeda_na_tabela

    async def fetchval(self, *_a: Any, **_k: Any) -> str | None:
        return self._moeda


def _inventario(moeda_na_tabela: str | None, *, acesso: bool = True) -> Any:
    async def run(op: Any, **_k: Any) -> Any:
        return await op(_ConnComMoeda(moeda_na_tabela))

    pilha = ExitStack()
    pilha.enter_context(patch("src.db.connection.run_with_reconnect", run))
    pilha.enter_context(
        patch(
            "src.db.repositories.manager_meta_account_access.can_manager_access",
            AsyncMock(return_value=acesso),
        )
    )
    return pilha


def _negacao_real(tool: Any, args: dict[str, Any], moeda_na_tabela: str | None) -> Any:
    """Gestor sem acesso: gate REAL da Graph (`run_meta_graph_get`) com audit mockado."""

    async def corre() -> tuple[dict[str, Any], AsyncMock]:
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=MagicMock())
        cm.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=cm)
        audit = AsyncMock()
        with (
            _inventario(moeda_na_tabela, acesso=False),
            patch("src.meta_ads.reports.connection.get_pool", return_value=pool),
            patch("src.meta_ads.reports.audit_log.record", audit),
        ):
            return await tool(args), audit

    return corre()


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
    g = AsyncMock(side_effect=[insights or {"data": []}])

    async def listar(
        ctx: Any, act: str, level: str, status: str | None, limit: int, operacao: str = ""
    ) -> tuple[list[dict[str, Any]], bool]:
        assert status == "ACTIVE"
        assert operacao == "meta_get_budget_pacing"
        if level == "campaign":
            return campanhas, trunc_camp
        return conjuntos, trunc_adset

    with (
        patch.object(modulo, "run_meta_graph_get", g),
        _inventario(moeda),
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
    ins = g.await_args_list[0].kwargs
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
    g.assert_not_awaited()  # sem dia fechado nao ha insights, e a moeda nao vem da Graph
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
    assert r["total"]["gasto_fechado_ativas_brl"] is None


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
    assert t["gasto_fechado_ativas_brl"] == 1500.0
    assert t["orcamento_diario_brl"] == 150.0
    assert t["projecao_mensal_brl"] == 4650.0


@pytest.mark.asyncio
async def test_total_com_tudo_legivel_nao_traz_motivo() -> None:
    r, _ = await _roda(
        hoje=date(2026, 10, 11),
        campanhas=[_camp("1", daily=100.0)],
        conjuntos=[],
        insights={"data": [_insight("1", "1000.00")]},
    )
    assert "total_motivo" not in r


@pytest.mark.asyncio
async def test_vitalicio_na_mistura_mantem_media_anula_projecao_e_explica() -> None:
    # Medido em 02/11: 1 dia fechado, gasto R$ 7,27, 7 campanhas ativas, 6 vitalicias.
    r, _ = await _roda(
        hoje=date(2026, 11, 2),
        campanhas=[_camp("1", daily=10.0), *(_camp(str(i), lifetime=100.0) for i in range(2, 8))],
        conjuntos=[],
        insights={"data": [_insight("1", "5.27"), _insight("2", "2.00")]},
    )
    t = r["total"]
    assert t["gasto_fechado_ativas_brl"] == 7.27
    assert t["media_diaria_brl"] == 7.27
    assert t["projecao_mensal_brl"] is None and t["orcamento_diario_brl"] is None
    assert "6 de 7" in r["total_motivo"] and "vitalício" in r["total_motivo"]


@pytest.mark.asyncio
async def test_vitalicio_nos_conjuntos_conta_no_motivo() -> None:
    r, _ = await _roda(
        hoje=date(2026, 10, 11),
        campanhas=[_camp("1")],
        conjuntos=[_adset("a", "1", lifetime=500.0)],
        insights={"data": [_insight("1", "100.00")]},
    )
    assert r["total"]["media_diaria_brl"] == 10.0
    assert "1 de 1" in r["total_motivo"] and "vitalício" in r["total_motivo"]


@pytest.mark.asyncio
async def test_motivo_de_gasto_nao_reportado() -> None:
    r, _ = await _roda(
        hoje=date(2026, 10, 11),
        campanhas=[_camp("1", daily=100.0), _camp("2", daily=50.0)],
        conjuntos=[],
        insights={"data": [_insight("1", None), _insight("2", "10.00")]},
    )
    assert r["total"]["media_diaria_brl"] is None
    assert "1 de 2" in r["total_motivo"] and "gasto" in r["total_motivo"]


@pytest.mark.asyncio
async def test_motivo_de_orcamento_ilegivel_mantem_a_projecao() -> None:
    r, _ = await _roda(
        hoje=date(2026, 10, 11),
        campanhas=[_camp("1"), _camp("2", daily=50.0)],
        conjuntos=[],
        insights={"data": [_insight("1", "10.00"), _insight("2", "10.00")]},
    )
    assert r["total"]["orcamento_diario_brl"] is None
    assert r["total"]["projecao_mensal_brl"] == 62.0
    assert "1 de 2" in r["total_motivo"] and "não legível" in r["total_motivo"]


@pytest.mark.asyncio
async def test_motivo_no_dia_1_truncado_e_sem_ativas() -> None:
    dia_1, _ = await _roda(
        hoje=date(2026, 10, 1), campanhas=[_camp("1", daily=1.0)], conjuntos=[], insights=None
    )
    assert "dia fechado" in dia_1["total_motivo"] and "orçamento" in dia_1["total_motivo"]
    assert dia_1["total"]["orcamento_diario_brl"] is None
    cortada, _ = await _roda(
        hoje=date(2026, 10, 11),
        campanhas=[_camp("1", daily=1.0)],
        conjuntos=[],
        insights=None,
        trunc_camp=True,
    )
    assert "incompleta" in cortada["total_motivo"]
    vazia, _ = await _roda(hoje=date(2026, 10, 11), campanhas=[], conjuntos=[], insights=None)
    assert "Nenhuma campanha ativa" in vazia["total_motivo"]


@pytest.mark.asyncio
async def test_moeda_diferente_de_brl_e_erro() -> None:
    r, g = await _roda(
        hoje=date(2026, 10, 11), campanhas=[], conjuntos=[], insights=None, moeda="USD"
    )
    assert r["status"] == "error"
    assert "USD" in r["error_message"]
    g.assert_not_awaited()


@pytest.mark.asyncio
async def test_falha_da_graph_vira_erro() -> None:
    g = AsyncMock(side_effect=RuntimeError("boom"))
    with (
        _inventario("BRL"),
        patch.object(modulo, "run_meta_graph_get", g),
        patch.object(modulo, "listar_entidades", AsyncMock(return_value=([], False))),
        patch.object(
            modulo, "resolve_meta_account_today", AsyncMock(return_value=date(2026, 10, 11))
        ),
        pytest.raises(RuntimeError, match="boom"),
    ):
        await modulo.meta_get_budget_pacing({"ad_account_id": _CONTA})


@pytest.mark.asyncio
async def test_campanha_pausada_com_gasto_aparece_fora_do_escopo() -> None:
    r, _ = await _roda(
        hoje=date(2026, 10, 11),
        campanhas=[_camp("1", daily=100.0)],
        conjuntos=[],
        insights={"data": [_insight("1", "1000.00"), _insight("9", "400.00")]},
    )
    t = r["total"]
    assert [c["campaign_id"] for c in r["campaigns"]] == ["1"]
    assert t["gasto_fechado_ativas_brl"] == 1000.0
    assert t["gasto_fora_do_escopo_brl"] == 400.0
    assert "gasto_fechado_brl" not in t


@pytest.mark.asyncio
async def test_linha_nao_ativa_devolvida_apesar_do_filtro_e_descartada() -> None:
    pausada_c = {**_camp("2", daily=500.0), "effective_status": "PAUSED"}
    pausado_a = {**_adset("20", "1", daily=300.0), "effective_status": "ADSET_PAUSED"}
    r, _ = await _roda(
        hoje=date(2026, 10, 11),
        campanhas=[_camp("1"), pausada_c],
        conjuntos=[_adset("10", "1", daily=100.0), pausado_a],
        insights={"data": [_insight("1", "1000.00")]},
    )
    assert [c["campaign_id"] for c in r["campaigns"]] == ["1"]
    assert r["campaigns"][0]["orcamento_diario_brl"] == 100.0


@pytest.mark.asyncio
async def test_todas_pausadas_nao_esconde_o_gasto_do_mes() -> None:
    r, _ = await _roda(
        hoje=date(2026, 10, 11),
        campanhas=[],
        conjuntos=[],
        insights={"data": [_insight("9", "400.00"), _insight("8", "100.50")]},
    )
    assert r["campaigns"] == []
    assert r["total"]["gasto_fechado_ativas_brl"] == 0.0
    assert r["total"]["gasto_fora_do_escopo_brl"] == 500.5


@pytest.mark.asyncio
async def test_gasto_fora_do_escopo_e_null_com_insights_truncado() -> None:
    r, _ = await _roda(
        hoje=date(2026, 10, 11),
        campanhas=[_camp("1", daily=100.0)],
        conjuntos=[],
        insights={"data": [_insight("9", "400.00")], "paging": {"next": "https://x"}},
    )
    assert r["total"]["gasto_fora_do_escopo_brl"] is None


@pytest.mark.asyncio
async def test_gasto_fora_do_escopo_e_null_com_campanhas_truncadas_ou_dia_1() -> None:
    r, _ = await _roda(
        hoje=date(2026, 10, 11),
        campanhas=[_camp("1", daily=100.0)],
        conjuntos=[],
        insights={"data": [_insight("9", "400.00")]},
        trunc_camp=True,
    )
    assert r["total"]["gasto_fora_do_escopo_brl"] is None
    r, _ = await _roda(hoje=date(2026, 10, 1), campanhas=[], conjuntos=[], insights=None)
    assert r["total"]["gasto_fora_do_escopo_brl"] is None
    assert r["total"]["gasto_fechado_ativas_brl"] is None


@pytest.mark.asyncio
async def test_spend_nao_reportado_fora_do_escopo_torna_o_total_fora_null() -> None:
    r, _ = await _roda(
        hoje=date(2026, 10, 11),
        campanhas=[],
        conjuntos=[],
        insights={"data": [_insight("9", None), _insight("8", "10.00")]},
    )
    assert r["total"]["gasto_fora_do_escopo_brl"] is None


@pytest.mark.asyncio
async def test_orcamento_nulo_nao_esconde_gasto_nem_projecao() -> None:
    r, _ = await _roda(
        hoje=date(2026, 10, 11),
        campanhas=[_camp("1")],
        conjuntos=[_adset("a", "1")],
        insights={"data": [_insight("1", "1000.00")]},
    )
    c = r["campaigns"][0]
    assert c["orcamento_diario_brl"] is None
    assert c["gasto_fechado_brl"] == 1000.0
    assert c["media_diaria_brl"] == 100.0
    assert c["projecao_mensal_brl"] == 3100.0
    assert c["projecao_vs_orcamento_pct"] is None


@pytest.mark.asyncio
async def test_conjunto_com_end_time_vencido_sai_do_orcamento_e_e_contado() -> None:
    vencido = {**_adset("b", "1", daily=900.0), "end_time": "2026-10-05T23:59:59-0300"}
    futuro = {**_adset("a", "1", daily=100.0), "end_time": "2026-10-20T23:59:59-0300"}
    r, _ = await _roda(
        hoje=date(2026, 10, 11),
        campanhas=[_camp("1")],
        conjuntos=[vencido, futuro],
        insights={"data": [_insight("1", "10.00")]},
    )
    assert r["campaigns"][0]["orcamento_diario_brl"] == 100.0
    assert r["excluidos_por_data_final"] == {"campanhas": 0, "conjuntos": 1}
    assert "1 conjunto" in r["escopo"]


@pytest.mark.asyncio
async def test_campanha_com_stop_time_vencido_sai_da_lista_e_o_gasto_vai_para_fora() -> None:
    velha = {**_camp("1", daily=100.0), "stop_time": "2026-10-03T00:00:00-0300"}
    r, _ = await _roda(
        hoje=date(2026, 10, 11),
        campanhas=[velha, _camp("2", daily=50.0)],
        conjuntos=[],
        insights={"data": [_insight("1", "300.00"), _insight("2", "100.00")]},
    )
    assert [c["campaign_id"] for c in r["campaigns"]] == ["2"]
    assert r["excluidos_por_data_final"] == {"campanhas": 1, "conjuntos": 0}
    assert r["total"]["gasto_fechado_ativas_brl"] == 100.0
    assert r["total"]["gasto_fora_do_escopo_brl"] == 300.0


@pytest.mark.asyncio
async def test_data_final_de_hoje_ou_futura_nao_exclui_e_ilegivel_nao_exclui() -> None:
    hoje_ = {**_camp("1", daily=10.0), "stop_time": "2026-10-11T23:59:59-0300"}
    lixo = {**_camp("2", daily=10.0), "stop_time": "amanha"}
    r, _ = await _roda(
        hoje=date(2026, 10, 11),
        campanhas=[hoje_, lixo],
        conjuntos=[],
        insights={"data": []},
    )
    assert len(r["campaigns"]) == 2


@pytest.mark.asyncio
async def test_vitalicio_em_conjunto_usa_flag_propria_sem_valor_unico() -> None:
    r, _ = await _roda(
        hoje=date(2026, 10, 11),
        campanhas=[_camp("1")],
        conjuntos=[_adset("a", "1", lifetime=500.0)],
        insights={"data": [_insight("1", "100.00")]},
    )
    c = r["campaigns"][0]
    assert c["tipo_orcamento"] == "vitalicio"
    assert c["orcamento_vitalicio_brl"] is None
    assert c["gasto_fechado_brl"] == 100.0


@pytest.mark.asyncio
async def test_falha_ao_resolver_o_relogio_da_conta_vira_erro() -> None:
    g = AsyncMock()
    with (
        patch.object(modulo, "run_meta_graph_get", g),
        patch.object(
            modulo, "resolve_meta_account_today", AsyncMock(side_effect=RuntimeError("db fora"))
        ),
        pytest.raises(RuntimeError, match="db fora"),
    ):
        await modulo.meta_get_budget_pacing({"ad_account_id": _CONTA})
    g.assert_not_awaited()


# ---------- moeda lida do inventario (decisao de 10/11): sem chamada de moeda a Graph ----------


async def _roda_com_inventario(moeda_na_tabela: str | None) -> tuple[dict[str, Any], AsyncMock]:
    async def graph(**kw: Any) -> dict[str, Any]:
        assert kw["params"] != {"fields": "currency"}, "a moeda nao vem mais da Graph"
        return {"data": []}

    g = AsyncMock(side_effect=graph)
    listar = AsyncMock(return_value=([], False))
    with (
        _inventario(moeda_na_tabela),
        patch.object(modulo, "run_meta_graph_get", g),
        patch.object(modulo, "listar_entidades", listar),
        patch.object(
            modulo, "resolve_meta_account_today", AsyncMock(return_value=date(2026, 10, 1))
        ),
    ):
        r = await modulo.meta_get_budget_pacing({"ad_account_id": _CONTA})
    return r, listar


@pytest.mark.asyncio
async def test_conta_brl_no_inventario_calcula_sem_chamar_a_graph_de_moeda() -> None:
    r, _ = await _roda_com_inventario("BRL")
    assert r["status"] == "success"


@pytest.mark.asyncio
@pytest.mark.parametrize("moeda_na_tabela", ["USD", None])
async def test_conta_nao_brl_no_inventario_devolve_o_envelope_de_moeda(
    moeda_na_tabela: str | None,
) -> None:
    r, listar = await _roda_com_inventario(moeda_na_tabela)
    assert r == {
        "status": "error",
        "error_message": (
            f"conta Meta em moeda {moeda_na_tabela!r}: o pacing só é calculado para contas em BRL"
        ),
    }
    listar.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("moeda_na_tabela", ["USD", "BRL"])
async def test_sem_acesso_a_negacao_do_gate_vale_e_a_moeda_nao_vaza(
    moeda_na_tabela: str,
) -> None:
    with patch.object(
        modulo, "resolve_meta_account_today", AsyncMock(return_value=date(2026, 10, 11))
    ):
        r, audit = await _negacao_real(
            modulo.meta_get_budget_pacing, {"ad_account_id": _CONTA}, moeda_na_tabela
        )
    assert r["status"] == "denied" and "moeda" not in r["error_message"]
    audit.assert_awaited_once()
    k = audit.call_args.kwargs
    assert k["status"] == "denied" and k["operation"] == "meta_get_budget_pacing"
    assert k["customer_id"] == _CONTA and k["platform"] == "meta"
