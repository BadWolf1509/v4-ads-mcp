"""GAQL queries for performance analysis tools."""

from datetime import date

from src.google_ads.queries._common import gaql_date_clause


def campaign_performance_query(start: date, end: date, status: str, limit: int) -> str:
    status_clause = "" if status == "all" else f"AND campaign.status = '{status.upper()}'"
    return f"""
        SELECT
          campaign.id, campaign.name, campaign.status,
          campaign.advertising_channel_type,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM campaign
        WHERE {gaql_date_clause(start, end)} {status_clause}
        ORDER BY metrics.cost_micros DESC
        LIMIT {limit}
    """.strip()


def ad_group_performance_query(start: date, end: date, status: str, limit: int) -> str:
    status_clause = "" if status == "all" else f"AND ad_group.status = '{status.upper()}'"
    return f"""
        SELECT
          ad_group.id, ad_group.name, ad_group.status,
          campaign.id, campaign.name,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM ad_group
        WHERE {gaql_date_clause(start, end)} {status_clause}
        ORDER BY metrics.cost_micros DESC
        LIMIT {limit}
    """.strip()


def device_performance_query(start: date, end: date) -> str:
    return f"""
        SELECT
          segments.device,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM customer
        WHERE {gaql_date_clause(start, end)}
    """.strip()


def geo_performance_query(start: date, end: date, limit: int) -> str:
    """Geographic performance from geographic_view (country-level criterion)."""
    return f"""
        SELECT
          geographic_view.country_criterion_id,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM geographic_view
        WHERE {gaql_date_clause(start, end)}
        ORDER BY metrics.cost_micros DESC
        LIMIT {limit}
    """.strip()


def hourly_performance_query(start: date, end: date) -> str:
    return f"""
        SELECT
          segments.hour, segments.day_of_week,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM customer
        WHERE {gaql_date_clause(start, end)}
    """.strip()
