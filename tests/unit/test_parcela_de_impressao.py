"""Parcela de impressão nas linhas de `level='campaign'` (spec 2026-10-02, §3.2).

Os cinco campos `search_*impression_share` são `optional` no proto (v24). Medido em 02/10
na Hosp Ocular: campanha SMART/LOCAL/VIDEO e campanha de pesquisa sem impressão vêm SEM o
campo (o `impressions` delas vem presente, `0`); a de pesquisa com impressão vem com ele —
inclusive `0.0999`, o "< 10%" do Google. Ler o atributo direto devolve `0.0` para o campo
ausente: o zero falso que a spec proíbe. A regra é presença no proto.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from google.ads.googleads.v24.common.types.metrics import Metrics

from src.google_ads.performance_breakdown import parse_performance_row
from src.google_ads.queries._common import metrica_opcional
from src.google_ads.queries.performance import campaign_performance_query

_CAMPOS = (
    "search_impression_share",
    "search_budget_lost_impression_share",
    "search_rank_lost_impression_share",
    "search_top_impression_share",
    "search_absolute_top_impression_share",
)


def _linha(metrics: Metrics) -> SimpleNamespace:
    return SimpleNamespace(
        campaign=SimpleNamespace(
            id=1,
            name="c",
            status=SimpleNamespace(name="ENABLED"),
            advertising_channel_type=SimpleNamespace(name="SEARCH"),
        ),
        metrics=metrics,
    )


def test_campo_ausente_no_proto_vira_none_e_nao_zero() -> None:
    vazio = Metrics(impressions=0)
    assert vazio.search_impression_share == 0.0  # o zero falso que a leitura direta daria
    assert metrica_opcional(vazio, "search_impression_share") is None


def test_campo_presente_devolve_o_valor_inclusive_zero_e_o_menor_que_10() -> None:
    assert (
        metrica_opcional(Metrics(search_impression_share=0.42), "search_impression_share") == 0.42
    )
    assert metrica_opcional(Metrics(search_impression_share=0.0), "search_impression_share") == 0.0
    assert (
        metrica_opcional(Metrics(search_top_impression_share=0.0999), "search_top_impression_share")
        == 0.0999
    )


def test_objeto_falso_sem_o_atributo_vira_none() -> None:
    """Os testes do modulo usam SimpleNamespace, onde `in` nao funciona."""
    assert metrica_opcional(SimpleNamespace(), "search_impression_share") is None
    assert (
        metrica_opcional(SimpleNamespace(search_impression_share=0.3), "search_impression_share")
        == 0.3
    )


def test_linha_de_campanha_traz_a_parcela_de_impressao() -> None:
    cheia = Metrics(
        impressions=100,
        search_impression_share=0.5517,
        search_budget_lost_impression_share=0.229,
        search_rank_lost_impression_share=0.2193,
        search_top_impression_share=0.4402,
        search_absolute_top_impression_share=0.3193,
    )
    r = parse_performance_row(_linha(cheia), "campaign", None)
    assert r["parcela_impressao"] == 0.5517
    assert r["perdida_orcamento"] == 0.229
    assert r["perdida_classificacao"] == 0.2193
    assert r["parcela_topo"] == 0.4402
    assert r["parcela_topo_absoluto"] == 0.3193


def test_campanha_sem_o_campo_traz_none_nos_cinco() -> None:
    r = parse_performance_row(_linha(Metrics(impressions=0)), "campaign", None)
    for chave in (
        "parcela_impressao",
        "perdida_orcamento",
        "perdida_classificacao",
        "parcela_topo",
        "parcela_topo_absoluto",
    ):
        assert r[chave] is None, chave


def test_query_de_campanha_pede_os_cinco_campos() -> None:
    gaql, _ = campaign_performance_query(date(2026, 9, 1), date(2026, 9, 30), "enabled", 10)
    for campo in _CAMPOS:
        assert f"metrics.{campo}" in gaql, campo
