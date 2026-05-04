"""GAQL queries for client-report tools."""

from datetime import date

from src.google_ads.queries._common import gaql_date_clause


def funnel_query(start: date, end: date) -> str:
    """Aggregate funnel metrics from customer-level for the period."""
    return f"""
        SELECT
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value
        FROM customer
        WHERE {gaql_date_clause(start, end)}
    """.strip()


def top_keywords_query(start: date, end: date, top_n: int) -> str:
    """Top N keywords ordered by metric (caller decides via ORDER BY at fetch)."""
    return f"""
        SELECT
          ad_group_criterion.criterion_id,
          ad_group_criterion.keyword.text,
          ad_group_criterion.keyword.match_type,
          ad_group.id, ad_group.name,
          campaign.id, campaign.name,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM keyword_view
        WHERE {gaql_date_clause(start, end)}
          AND ad_group_criterion.status = 'ENABLED'
        ORDER BY metrics.cost_micros DESC
        LIMIT {top_n}
    """.strip()


def top_creatives_query(start: date, end: date, top_n: int) -> str:
    """Top N RSAs ordered by metric."""
    return f"""
        SELECT
          ad_group_ad.ad.id,
          ad_group_ad.ad.responsive_search_ad.headlines,
          ad_group_ad.ad.responsive_search_ad.descriptions,
          ad_group_ad.ad_strength,
          ad_group.id, ad_group.name,
          campaign.id, campaign.name,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM ad_group_ad
        WHERE {gaql_date_clause(start, end)}
          AND ad_group_ad.status = 'ENABLED'
        ORDER BY metrics.cost_micros DESC
        LIMIT {top_n}
    """.strip()
