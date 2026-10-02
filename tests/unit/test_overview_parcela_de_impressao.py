"""Parcela de impressão no `get_account_overview` (spec 2026-10-02, §3.2).

Em `FROM customer` só três campos existem (medido em 02/10: topo e topo absoluto são
recusados pela API nesse recurso). A parcela não soma: ela vem de uma linha só (`customer`
sem segmento devolve uma), e com mais de uma linha — ou nenhuma — o valor é `None`.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from google.ads.googleads.v24.common.types.metrics import Metrics

from src.google_ads.queries.overview import overview_query
from src.mcp.tools.get_account_overview import _aggregate, _row_formatter


def _row(**metricas: float) -> SimpleNamespace:
    return SimpleNamespace(
        metrics=Metrics(impressions=10, clicks=1, cost_micros=1_000_000, **metricas)
    )


def test_query_pede_os_tres_campos_da_conta_e_nao_os_de_topo() -> None:
    gaql, _ = overview_query(date(2026, 9, 1), date(2026, 9, 30))
    assert "metrics.search_impression_share" in gaql
    assert "metrics.search_budget_lost_impression_share" in gaql
    assert "metrics.search_rank_lost_impression_share" in gaql
    assert "search_top_impression_share" not in gaql
    assert "search_absolute_top_impression_share" not in gaql


def test_linha_com_os_campos_chega_ao_agregado() -> None:
    linha = _row(
        search_impression_share=0.5468,
        search_budget_lost_impression_share=0.2339,
        search_rank_lost_impression_share=0.2194,
    )
    agg = _aggregate([_row_formatter(linha)])
    assert agg["parcela_impressao"] == 0.5468
    assert agg["perdida_orcamento"] == 0.2339
    assert agg["perdida_classificacao"] == 0.2194


def test_campo_ausente_vira_none() -> None:
    agg = _aggregate([_row_formatter(_row())])
    assert agg["parcela_impressao"] is None
    assert agg["perdida_orcamento"] is None
    assert agg["perdida_classificacao"] is None


def test_periodo_sem_linha_traz_none() -> None:
    agg = _aggregate([])
    assert agg["parcela_impressao"] is None


def test_mais_de_uma_linha_nao_soma_parcela() -> None:
    a = _row_formatter(_row(search_impression_share=0.5))
    b = _row_formatter(_row(search_impression_share=0.3))
    agg = _aggregate([a, b])
    assert agg["parcela_impressao"] is None
    assert agg["impressions"] == 20  # as contagens seguem somando
