"""GAQL queries for performance analysis tools.

Cada funcao devolve `(gaql, filtros)`: `filtros` e o recorte que a query aplica,
montado junto da clausula do WHERE que o aplica. As tools o ecoam em
`filters_applied` (spec 2026-09-25, padrao do F191).
"""

from datetime import date
from typing import Any

from src.google_ads.queries._common import gaql_date_clause, janela_aplicada


def campaign_performance_query(
    start: date, end: date, status: str, limit: int
) -> tuple[str, dict[str, Any]]:
    filtros: dict[str, Any] = {"date_range": janela_aplicada(start, end)}
    status_clause = ""
    if status != "all":
        status_clause = f"AND campaign.status = '{status.upper()}'"
        filtros["campaign_status"] = status.upper()
    gaql = f"""
        SELECT
          campaign.id, campaign.name, campaign.status,
          campaign.advertising_channel_type,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM campaign
        WHERE {gaql_date_clause(start, end)} {status_clause}
        ORDER BY metrics.cost_micros DESC
        LIMIT {limit + 1}
    """.strip()
    return gaql, filtros


def ad_group_performance_query(
    start: date, end: date, status: str, limit: int
) -> tuple[str, dict[str, Any]]:
    filtros: dict[str, Any] = {"date_range": janela_aplicada(start, end)}
    status_clause = ""
    if status != "all":
        status_clause = f"AND ad_group.status = '{status.upper()}'"
        filtros["ad_group_status"] = status.upper()
    gaql = f"""
        SELECT
          ad_group.id, ad_group.name, ad_group.status,
          campaign.id, campaign.name,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM ad_group
        WHERE {gaql_date_clause(start, end)} {status_clause}
        ORDER BY metrics.cost_micros DESC
        LIMIT {limit + 1}
    """.strip()
    return gaql, filtros


def device_performance_query(start: date, end: date) -> tuple[str, dict[str, Any]]:
    gaql = f"""
        SELECT
          segments.device,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM customer
        WHERE {gaql_date_clause(start, end)}
    """.strip()
    return gaql, {"date_range": janela_aplicada(start, end)}


def geo_performance_query(start: date, end: date, limit: int) -> tuple[str, dict[str, Any]]:
    """Geographic performance from geographic_view (country-level criterion)."""
    gaql = f"""
        SELECT
          geographic_view.country_criterion_id,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM geographic_view
        WHERE {gaql_date_clause(start, end)}
        ORDER BY metrics.cost_micros DESC
        LIMIT {limit + 1}
    """.strip()
    return gaql, {"date_range": janela_aplicada(start, end)}


def hourly_performance_query(start: date, end: date) -> tuple[str, dict[str, Any]]:
    gaql = f"""
        SELECT
          segments.hour, segments.day_of_week,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM customer
        WHERE {gaql_date_clause(start, end)}
    """.strip()
    return gaql, {"date_range": janela_aplicada(start, end)}
