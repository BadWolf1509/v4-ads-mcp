"""GAQL queries for visao geral tools (account_overview, budget_pacing)."""

from datetime import date

from src.google_ads.queries._common import gaql_date_clause


def overview_query(date_start: date, date_end: date) -> str:
    """Aggregate metrics across all enabled campaigns for the date range."""
    return f"""
        SELECT
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value,
          metrics.ctr,
          metrics.average_cpc,
          metrics.cost_per_conversion
        FROM customer
        WHERE {gaql_date_clause(date_start, date_end)}
    """.strip()


def budget_pacing_query(limit: int = 100) -> str:
    """Per-campaign current budget + MTD spend.

    Returns one row per enabled campaign with budget amount + month-to-date metrics.

    F98 — `limit + 1` (a linha extra revela o corte) **e** `ORDER BY` explícito:
    o tool ordena por gasto DESC no fim, então cortar um conjunto não-ordenado
    entregaria N campanhas arbitrárias reordenadas entre si, parecendo o topo de
    gasto da conta sem ser — a classe F88 ("truncar e depois ordenar").
    """
    return f"""
        SELECT
          campaign.id,
          campaign.name,
          campaign.status,
          campaign_budget.amount_micros,
          campaign_budget.delivery_method,
          metrics.cost_micros
        FROM campaign
        WHERE campaign.status = 'ENABLED'
          AND segments.date DURING THIS_MONTH
        ORDER BY metrics.cost_micros DESC
        LIMIT {limit + 1}
    """.strip()
