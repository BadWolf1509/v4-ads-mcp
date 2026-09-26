"""GAQL queries for tactical optimization tools."""

from datetime import date
from typing import Any

from src.google_ads.queries._common import (
    build_metric_filter_clause,
    filtros_de_metrica,
    gaql_date_clause,
    janela_aplicada,
)


def keyword_performance_query(
    start: date,
    end: date,
    status: str,
    limit: int,
    *,
    min_cost_brl: float | None = None,
    min_clicks: int | None = None,
    min_conversions: float | None = None,
) -> tuple[str, dict[str, Any]]:
    filtros: dict[str, Any] = {"date_range": janela_aplicada(start, end)}
    status_clause = ""
    if status != "all":
        status_clause = f"AND ad_group_criterion.status = '{status.upper()}'"
        filtros["criterion_status"] = status.upper()
    metric_clause = build_metric_filter_clause(min_cost_brl, min_clicks, min_conversions)
    filtros.update(filtros_de_metrica(min_cost_brl, min_clicks, min_conversions))
    gaql = f"""
        SELECT
          ad_group_criterion.criterion_id,
          ad_group_criterion.keyword.text,
          ad_group_criterion.keyword.match_type,
          ad_group_criterion.status,
          ad_group_criterion.negative,
          ad_group_criterion.quality_info.quality_score,
          ad_group_criterion.quality_info.creative_quality_score,
          ad_group_criterion.quality_info.post_click_quality_score,
          ad_group_criterion.quality_info.search_predicted_ctr,
          ad_group_criterion.position_estimates.first_page_cpc_micros,
          ad_group_criterion.position_estimates.top_of_page_cpc_micros,
          ad_group.id, ad_group.name,
          campaign.id, campaign.name,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM keyword_view
        WHERE {gaql_date_clause(start, end)} {status_clause} {metric_clause}
        ORDER BY metrics.cost_micros DESC
        LIMIT {limit + 1}
    """.strip()
    return gaql, filtros


def search_terms_query(
    start: date,
    end: date,
    limit: int,
    *,
    min_cost_brl: float | None = None,
    min_clicks: int | None = None,
    min_conversions: float | None = None,
) -> tuple[str, dict[str, Any]]:
    filtros: dict[str, Any] = {"date_range": janela_aplicada(start, end)}
    metric_clause = build_metric_filter_clause(min_cost_brl, min_clicks, min_conversions)
    filtros.update(filtros_de_metrica(min_cost_brl, min_clicks, min_conversions))
    gaql = f"""
        SELECT
          search_term_view.search_term,
          search_term_view.status,
          ad_group.id, ad_group.name,
          campaign.id, campaign.name,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM search_term_view
        WHERE {gaql_date_clause(start, end)} {metric_clause}
        ORDER BY metrics.cost_micros DESC
        LIMIT {limit + 1}
    """.strip()
    return gaql, filtros


def negative_keywords_audit_query() -> tuple[str, dict[str, Any]]:
    """Negativas de keyword no NIVEL DE CAMPANHA — so elas.

    Negativas de grupo (`ad_group_criterion`) e listas compartilhadas
    (`shared_criterion`) nao entram: o `nivel` no `filtros` diz isso na resposta
    (spec 2026-09-25, §4.3). Cobrir a conta inteira e frente propria.
    """
    gaql = """
        SELECT
          campaign_criterion.criterion_id,
          campaign_criterion.negative,
          campaign_criterion.keyword.text,
          campaign_criterion.keyword.match_type,
          campaign.id,
          campaign.name
        FROM campaign_criterion
        WHERE campaign_criterion.negative = true
          AND campaign_criterion.type = 'KEYWORD'
    """.strip()
    filtros: dict[str, Any] = {"nivel": "campanha", "negative": True, "criterion_type": "KEYWORD"}
    return gaql, filtros


def ad_performance_query(
    start: date, end: date, status: str, limit: int
) -> tuple[str, dict[str, Any]]:
    filtros: dict[str, Any] = {"date_range": janela_aplicada(start, end)}
    status_clause = ""
    if status != "all":
        status_clause = f"AND ad_group_ad.status = '{status.upper()}'"
        filtros["ad_status"] = status.upper()
    gaql = f"""
        SELECT
          ad_group_ad.ad.id,
          ad_group_ad.status,
          ad_group_ad.ad.type,
          ad_group_ad.ad.responsive_search_ad.headlines,
          ad_group_ad.ad.responsive_search_ad.descriptions,
          ad_group_ad.ad.final_urls,
          ad_group_ad.ad_strength,
          ad_group.id, ad_group.name,
          campaign.id, campaign.name,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM ad_group_ad
        WHERE {gaql_date_clause(start, end)} {status_clause}
        ORDER BY metrics.cost_micros DESC
        LIMIT {limit + 1}
    """.strip()
    return gaql, filtros


def audience_performance_query(start: date, end: date, limit: int) -> tuple[str, dict[str, Any]]:
    gaql = f"""
        SELECT
          ad_group_audience_view.resource_name,
          ad_group_criterion.criterion_id,
          ad_group_criterion.user_list.user_list,
          ad_group_criterion.user_interest.user_interest_category,
          ad_group.id, ad_group.name,
          campaign.id, campaign.name,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM ad_group_audience_view
        WHERE {gaql_date_clause(start, end)}
        ORDER BY metrics.cost_micros DESC
        LIMIT {limit + 1}
    """.strip()
    return gaql, {"date_range": janela_aplicada(start, end)}


def conversion_actions_query(limit: int = 100) -> tuple[str, dict[str, Any]]:
    """F98 — `limit + 1`: a linha extra é a sentinela que revela o corte.

    Nao corta nada: o `filtros` vazio e o eco honesto, nao uma ausencia.
    """
    gaql = f"""
        SELECT
          conversion_action.id,
          conversion_action.name,
          conversion_action.status,
          conversion_action.category,
          conversion_action.type,
          conversion_action.counting_type,
          conversion_action.attribution_model_settings.attribution_model,
          conversion_action.value_settings.default_value,
          conversion_action.value_settings.always_use_default_value,
          conversion_action.primary_for_goal,
          conversion_action.include_in_conversions_metric
        FROM conversion_action
        LIMIT {limit + 1}
    """.strip()
    return gaql, {}
