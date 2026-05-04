"""GAQL queries for tactical optimization tools."""

from datetime import date

from src.google_ads.queries._common import gaql_date_clause


def keyword_performance_query(start: date, end: date, status: str, limit: int) -> str:
    status_clause = "" if status == "all" else f"AND ad_group_criterion.status = '{status.upper()}'"
    return f"""
        SELECT
          ad_group_criterion.criterion_id,
          ad_group_criterion.keyword.text,
          ad_group_criterion.keyword.match_type,
          ad_group_criterion.status,
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
        WHERE {gaql_date_clause(start, end)} {status_clause}
        ORDER BY metrics.cost_micros DESC
        LIMIT {limit}
    """.strip()


def search_terms_query(start: date, end: date, limit: int) -> str:
    return f"""
        SELECT
          search_term_view.search_term,
          search_term_view.status,
          ad_group.id, ad_group.name,
          campaign.id, campaign.name,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM search_term_view
        WHERE {gaql_date_clause(start, end)}
        ORDER BY metrics.cost_micros DESC
        LIMIT {limit}
    """.strip()


def negative_keywords_audit_query() -> str:
    """Negative keywords applied at campaign level."""
    return """
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


def ad_performance_query(start: date, end: date, status: str, limit: int) -> str:
    status_clause = "" if status == "all" else f"AND ad_group_ad.status = '{status.upper()}'"
    return f"""
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
        LIMIT {limit}
    """.strip()


def audience_performance_query(start: date, end: date, limit: int) -> str:
    return f"""
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
        LIMIT {limit}
    """.strip()


def conversion_actions_query() -> str:
    return """
        SELECT
          conversion_action.id,
          conversion_action.name,
          conversion_action.status,
          conversion_action.category,
          conversion_action.type,
          conversion_action.counting_type,
          conversion_action.attribution_model_settings.attribution_model,
          conversion_action.value_settings.default_value,
          conversion_action.value_settings.always_use_default_value
        FROM conversion_action
    """.strip()
