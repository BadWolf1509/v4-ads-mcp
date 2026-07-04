"""Asserções de TEXTO GAQL nos query builders (overview / client_report / recommendations /
performance / tactical).

Os tools que consomem estes builders patcham `run_report` nos testes, então um typo
na string GAQL (campo errado, FROM errado, WHERE/ORDER BY quebrado) passa despercebido.
Estes testes chamam os builders diretos e asseveram os fragmentos GAQL esperados —
SELECT dos campos certos, FROM do recurso certo, cláusulas WHERE/ORDER BY/LIMIT chave.

Modelo: tests/unit/test_performance_breakdown.py (asserção de `FROM customer`,
`segments.device`, etc.). performance.py/tactical.py alimentam os 8 reports antigos
(get_campaign_performance, get_keyword_performance, etc.) que seguem em uso ativo
até a Fase 2B (soak) — typo aqui é prod quebrada.
"""

from datetime import date

from src.google_ads.queries.client_report import (
    funnel_query,
    top_creatives_query,
    top_keywords_query,
)
from src.google_ads.queries.overview import budget_pacing_query, overview_query
from src.google_ads.queries.performance import (
    ad_group_performance_query,
    campaign_performance_query,
    device_performance_query,
    geo_performance_query,
    hourly_performance_query,
)
from src.google_ads.queries.recommendations import recommendations_query
from src.google_ads.queries.tactical import (
    ad_performance_query,
    audience_performance_query,
    conversion_actions_query,
    keyword_performance_query,
    negative_keywords_audit_query,
    search_terms_query,
)

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


# ---------------------------------------------------------------------------
# performance.py
# ---------------------------------------------------------------------------


def test_campaign_performance_query_shape_status_filter_and_order() -> None:
    q = campaign_performance_query(_S, _E, "enabled", 10)
    assert "FROM campaign" in q
    for field in (
        "campaign.id",
        "campaign.name",
        "campaign.status",
        "campaign.advertising_channel_type",
        "metrics.impressions",
        "metrics.clicks",
        "metrics.cost_micros",
        "metrics.conversions",
        "metrics.conversions_value",
    ):
        assert field in q, f"faltou {field} no SELECT do campaign_performance_query"
    assert _DATE_CLAUSE in q
    assert "campaign.status = 'ENABLED'" in q
    assert "ORDER BY metrics.cost_micros DESC" in q
    assert "LIMIT 10" in q


def test_campaign_performance_query_status_all_omits_status_clause() -> None:
    q = campaign_performance_query(_S, _E, "all", 10)
    assert "campaign.status = " not in q


def test_ad_group_performance_query_shape_status_filter_and_order() -> None:
    q = ad_group_performance_query(_S, _E, "paused", 20)
    assert "FROM ad_group" in q
    for field in (
        "ad_group.id",
        "ad_group.name",
        "ad_group.status",
        "campaign.id",
        "campaign.name",
        "metrics.impressions",
        "metrics.clicks",
        "metrics.cost_micros",
        "metrics.conversions",
        "metrics.conversions_value",
    ):
        assert field in q, f"faltou {field} no SELECT do ad_group_performance_query"
    assert _DATE_CLAUSE in q
    assert "ad_group.status = 'PAUSED'" in q
    assert "ORDER BY metrics.cost_micros DESC" in q
    assert "LIMIT 20" in q


def test_ad_group_performance_query_status_all_omits_status_clause() -> None:
    q = ad_group_performance_query(_S, _E, "all", 20)
    assert "ad_group.status = " not in q


def test_device_performance_query_shape() -> None:
    q = device_performance_query(_S, _E)
    assert "FROM customer" in q
    for field in (
        "segments.device",
        "metrics.impressions",
        "metrics.clicks",
        "metrics.cost_micros",
        "metrics.conversions",
        "metrics.conversions_value",
    ):
        assert field in q, f"faltou {field} no SELECT do device_performance_query"
    assert _DATE_CLAUSE in q


def test_geo_performance_query_shape_and_order() -> None:
    q = geo_performance_query(_S, _E, 15)
    assert "FROM geographic_view" in q
    for field in (
        "geographic_view.country_criterion_id",
        "metrics.impressions",
        "metrics.clicks",
        "metrics.cost_micros",
        "metrics.conversions",
        "metrics.conversions_value",
    ):
        assert field in q, f"faltou {field} no SELECT do geo_performance_query"
    assert _DATE_CLAUSE in q
    assert "ORDER BY metrics.cost_micros DESC" in q
    assert "LIMIT 15" in q


def test_hourly_performance_query_shape() -> None:
    q = hourly_performance_query(_S, _E)
    assert "FROM customer" in q
    for field in (
        "segments.hour",
        "segments.day_of_week",
        "metrics.impressions",
        "metrics.clicks",
        "metrics.cost_micros",
        "metrics.conversions",
        "metrics.conversions_value",
    ):
        assert field in q, f"faltou {field} no SELECT do hourly_performance_query"
    assert _DATE_CLAUSE in q


# ---------------------------------------------------------------------------
# tactical.py
# ---------------------------------------------------------------------------


def test_keyword_performance_query_shape_status_filter_and_order() -> None:
    q = keyword_performance_query(_S, _E, "enabled", 25)
    assert "FROM keyword_view" in q
    for field in (
        "ad_group_criterion.criterion_id",
        "ad_group_criterion.keyword.text",
        "ad_group_criterion.keyword.match_type",
        "ad_group_criterion.status",
        "ad_group_criterion.negative",
        "ad_group_criterion.quality_info.quality_score",
        "ad_group_criterion.quality_info.creative_quality_score",
        "ad_group_criterion.quality_info.post_click_quality_score",
        "ad_group_criterion.quality_info.search_predicted_ctr",
        "ad_group_criterion.position_estimates.first_page_cpc_micros",
        "ad_group_criterion.position_estimates.top_of_page_cpc_micros",
        "ad_group.id",
        "ad_group.name",
        "campaign.id",
        "campaign.name",
        "metrics.impressions",
        "metrics.clicks",
        "metrics.cost_micros",
        "metrics.conversions",
        "metrics.conversions_value",
    ):
        assert field in q, f"faltou {field} no SELECT do keyword_performance_query"
    assert _DATE_CLAUSE in q
    assert "ad_group_criterion.status = 'ENABLED'" in q
    assert "ORDER BY metrics.cost_micros DESC" in q
    assert "LIMIT 25" in q


def test_keyword_performance_query_status_all_omits_status_clause() -> None:
    q = keyword_performance_query(_S, _E, "all", 25)
    assert "ad_group_criterion.status = " not in q


def test_keyword_performance_query_metric_filters_appended() -> None:
    q = keyword_performance_query(
        _S, _E, "enabled", 25, min_cost_brl=10.0, min_clicks=5, min_conversions=1.0
    )
    assert "AND metrics.cost_micros >= 10000000" in q
    assert "AND metrics.clicks >= 5" in q
    assert "AND metrics.conversions > 1.0" in q


def test_search_terms_query_shape_and_order() -> None:
    q = search_terms_query(_S, _E, 30)
    assert "FROM search_term_view" in q
    for field in (
        "search_term_view.search_term",
        "search_term_view.status",
        "ad_group.id",
        "ad_group.name",
        "campaign.id",
        "campaign.name",
        "metrics.impressions",
        "metrics.clicks",
        "metrics.cost_micros",
        "metrics.conversions",
        "metrics.conversions_value",
    ):
        assert field in q, f"faltou {field} no SELECT do search_terms_query"
    assert _DATE_CLAUSE in q
    assert "ORDER BY metrics.cost_micros DESC" in q
    assert "LIMIT 30" in q


def test_search_terms_query_metric_filters_appended() -> None:
    q = search_terms_query(_S, _E, 30, min_cost_brl=5.5, min_clicks=2)
    assert "AND metrics.cost_micros >= 5500000" in q
    assert "AND metrics.clicks >= 2" in q
    # min_conversions não informado -> cláusula de conversions ausente.
    assert "metrics.conversions >" not in q


def test_negative_keywords_audit_query_shape() -> None:
    q = negative_keywords_audit_query()
    assert "FROM campaign_criterion" in q
    for field in (
        "campaign_criterion.criterion_id",
        "campaign_criterion.negative",
        "campaign_criterion.keyword.text",
        "campaign_criterion.keyword.match_type",
        "campaign.id",
        "campaign.name",
    ):
        assert field in q, f"faltou {field} no SELECT do negative_keywords_audit_query"
    # Só negativas de tipo KEYWORD (não outros tipos de criterion negativo).
    assert "campaign_criterion.negative = true" in q
    assert "campaign_criterion.type = 'KEYWORD'" in q
    # Sem filtro de data — negativas não são segmentadas por período.
    assert "segments.date" not in q


def test_ad_performance_query_shape_status_filter_and_order() -> None:
    q = ad_performance_query(_S, _E, "enabled", 12)
    assert "FROM ad_group_ad" in q
    for field in (
        "ad_group_ad.ad.id",
        "ad_group_ad.status",
        "ad_group_ad.ad.type",
        "ad_group_ad.ad.responsive_search_ad.headlines",
        "ad_group_ad.ad.responsive_search_ad.descriptions",
        "ad_group_ad.ad.final_urls",
        "ad_group_ad.ad_strength",
        "ad_group.id",
        "ad_group.name",
        "campaign.id",
        "campaign.name",
        "metrics.impressions",
        "metrics.clicks",
        "metrics.cost_micros",
        "metrics.conversions",
        "metrics.conversions_value",
    ):
        assert field in q, f"faltou {field} no SELECT do ad_performance_query"
    assert _DATE_CLAUSE in q
    assert "ad_group_ad.status = 'ENABLED'" in q
    assert "ORDER BY metrics.cost_micros DESC" in q
    assert "LIMIT 12" in q


def test_ad_performance_query_status_all_omits_status_clause() -> None:
    q = ad_performance_query(_S, _E, "all", 12)
    assert "ad_group_ad.status = " not in q


def test_audience_performance_query_shape_and_order() -> None:
    q = audience_performance_query(_S, _E, 8)
    assert "FROM ad_group_audience_view" in q
    for field in (
        "ad_group_audience_view.resource_name",
        "ad_group_criterion.criterion_id",
        "ad_group_criterion.user_list.user_list",
        "ad_group_criterion.user_interest.user_interest_category",
        "ad_group.id",
        "ad_group.name",
        "campaign.id",
        "campaign.name",
        "metrics.impressions",
        "metrics.clicks",
        "metrics.cost_micros",
        "metrics.conversions",
        "metrics.conversions_value",
    ):
        assert field in q, f"faltou {field} no SELECT do audience_performance_query"
    assert _DATE_CLAUSE in q
    assert "ORDER BY metrics.cost_micros DESC" in q
    assert "LIMIT 8" in q


def test_conversion_actions_query_shape() -> None:
    q = conversion_actions_query()
    assert "FROM conversion_action" in q
    for field in (
        "conversion_action.id",
        "conversion_action.name",
        "conversion_action.status",
        "conversion_action.category",
        "conversion_action.type",
        "conversion_action.counting_type",
        "conversion_action.attribution_model_settings.attribution_model",
        "conversion_action.value_settings.default_value",
        "conversion_action.value_settings.always_use_default_value",
        "conversion_action.primary_for_goal",
        "conversion_action.include_in_conversions_metric",
    ):
        assert field in q, f"faltou {field} no SELECT do conversion_actions_query"
    # Sem filtro de data/status — lista todas as conversion actions da conta.
    assert "WHERE" not in q
