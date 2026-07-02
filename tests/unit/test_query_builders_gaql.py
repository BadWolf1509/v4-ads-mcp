"""Asserções de TEXTO GAQL nos query builders (overview / client_report / recommendations).

Os tools que consomem estes builders patcham `run_report` nos testes, então um typo
na string GAQL (campo errado, FROM errado, WHERE/ORDER BY quebrado) passa despercebido.
Estes testes chamam os builders diretos e asseveram os fragmentos GAQL esperados —
SELECT dos campos certos, FROM do recurso certo, cláusulas WHERE/ORDER BY/LIMIT chave.

Modelo: tests/unit/test_performance_breakdown.py (asserção de `FROM customer`,
`segments.device`, etc.).
"""

from datetime import date

from src.google_ads.queries.client_report import (
    funnel_query,
    top_creatives_query,
    top_keywords_query,
)
from src.google_ads.queries.overview import budget_pacing_query, overview_query
from src.google_ads.queries.recommendations import recommendations_query

_S, _E = date(2026, 1, 1), date(2026, 1, 31)

# Cláusula de data que gaql_date_clause emite pro range acima (formato ISO, aspas simples).
_DATE_CLAUSE = "segments.date BETWEEN '2026-01-01' AND '2026-01-31'"


# ---------------------------------------------------------------------------
# overview.py
# ---------------------------------------------------------------------------


def test_overview_query_selects_customer_metrics() -> None:
    q = overview_query(_S, _E)
    assert "FROM customer" in q
    for field in (
        "metrics.impressions",
        "metrics.clicks",
        "metrics.cost_micros",
        "metrics.conversions",
        "metrics.conversions_value",
        "metrics.ctr",
        "metrics.average_cpc",
        "metrics.cost_per_conversion",
    ):
        assert field in q, f"faltou {field} no SELECT do overview_query"


def test_overview_query_where_date_clause() -> None:
    q = overview_query(_S, _E)
    assert _DATE_CLAUSE in q


def test_budget_pacing_query_shape() -> None:
    q = budget_pacing_query()
    assert "FROM campaign" in q
    for field in (
        "campaign.id",
        "campaign.name",
        "campaign.status",
        "campaign_budget.amount_micros",
        "campaign_budget.delivery_method",
        "metrics.cost_micros",
    ):
        assert field in q, f"faltou {field} no SELECT do budget_pacing_query"
    # Só campanhas ativas, gasto do mês corrente.
    assert "campaign.status = 'ENABLED'" in q
    assert "segments.date DURING THIS_MONTH" in q


# ---------------------------------------------------------------------------
# client_report.py
# ---------------------------------------------------------------------------


def test_funnel_query_shape() -> None:
    q = funnel_query(_S, _E)
    assert "FROM customer" in q
    for field in (
        "metrics.impressions",
        "metrics.clicks",
        "metrics.cost_micros",
        "metrics.conversions",
        "metrics.conversions_value",
    ):
        assert field in q, f"faltou {field} no SELECT do funnel_query"
    assert _DATE_CLAUSE in q


def test_top_keywords_query_shape_and_order() -> None:
    q = top_keywords_query(_S, _E, 5)
    assert "FROM keyword_view" in q
    for field in (
        "ad_group_criterion.criterion_id",
        "ad_group_criterion.keyword.text",
        "ad_group_criterion.keyword.match_type",
        "ad_group.id",
        "campaign.id",
        "metrics.cost_micros",
    ):
        assert field in q, f"faltou {field} no SELECT do top_keywords_query"
    assert _DATE_CLAUSE in q
    assert "ad_group_criterion.status = 'ENABLED'" in q
    assert "ORDER BY metrics.cost_micros DESC" in q
    assert "LIMIT 5" in q


def test_top_keywords_query_limit_is_parameterized() -> None:
    assert "LIMIT 25" in top_keywords_query(_S, _E, 25)
    assert "LIMIT 5" not in top_keywords_query(_S, _E, 25)


def test_top_creatives_query_shape_and_order() -> None:
    q = top_creatives_query(_S, _E, 3)
    assert "FROM ad_group_ad" in q
    for field in (
        "ad_group_ad.ad.id",
        "ad_group_ad.ad.responsive_search_ad.headlines",
        "ad_group_ad.ad.responsive_search_ad.descriptions",
        "ad_group_ad.ad_strength",
        "campaign.name",
        "metrics.cost_micros",
    ):
        assert field in q, f"faltou {field} no SELECT do top_creatives_query"
    assert _DATE_CLAUSE in q
    assert "ad_group_ad.status = 'ENABLED'" in q
    assert "ORDER BY metrics.cost_micros DESC" in q
    assert "LIMIT 3" in q


# ---------------------------------------------------------------------------
# recommendations.py
# ---------------------------------------------------------------------------


def test_recommendations_query_shape() -> None:
    q = recommendations_query()
    assert "FROM recommendation" in q
    for field in (
        "recommendation.resource_name",
        "recommendation.type",
        "recommendation.dismissed",
    ):
        assert field in q, f"faltou {field} no SELECT do recommendations_query"
    # Só pendentes (não dispensadas).
    assert "recommendation.dismissed = false" in q
    # Métricas de impacto foram intencionalmente omitidas (docstring) — guard.
    assert "base_metrics" not in q
    assert "potential_metrics" not in q
