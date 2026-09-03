"""GAQL do ad_schedule (spec §3, §4.2, §4.3).

Superficie verificada: 02/09 por `validate_gaql` (campaign_criterion.ad_schedule.*,
bid_modifier, status; campaign_budget.explicitly_shared) e 03/09 por `run_gaql`
(conjunta segments.day_of_week x segments.hour sobre `campaign`, com metricas).
`segments.hour` chega como int 0..23; `metrics.cost_micros` chega como string.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from src.google_ads.ad_schedule import ENUM_MINUTO
from src.google_ads.queries._common import gaql_date_clause
from src.google_ads.queries._gaql import gaql_in_list

_STATUS_FILTER = {"enabled": "ENABLED", "paused": "PAUSED", "removed": "REMOVED"}


def _nome(x: Any) -> str:
    return x.name if hasattr(x, "name") else str(x)


def ad_schedule_query(*, campaign_ids: list[str] | None, status: str, limit: int) -> str:
    filtros = ["campaign_criterion.type = 'AD_SCHEDULE'"]
    if campaign_ids:
        filtros.append(
            f"campaign.id IN ({','.join(campaign_ids)})"
        )  # ids validados ^[0-9]+$ no schema
    if status in _STATUS_FILTER:
        filtros.append(f"campaign_criterion.status = '{_STATUS_FILTER[status]}'")
    return f"""
        SELECT campaign.id, campaign.name, campaign_criterion.criterion_id,
               campaign_criterion.resource_name,
               campaign_criterion.ad_schedule.day_of_week,
               campaign_criterion.ad_schedule.start_hour,
               campaign_criterion.ad_schedule.start_minute,
               campaign_criterion.ad_schedule.end_hour,
               campaign_criterion.ad_schedule.end_minute,
               campaign_criterion.bid_modifier, campaign_criterion.status
        FROM campaign_criterion
        WHERE {" AND ".join(filtros)}
        ORDER BY campaign.id, campaign_criterion.ad_schedule.day_of_week, campaign_criterion.ad_schedule.start_hour
        LIMIT {limit + 1}
    """.strip()


def parse_ad_schedule_row(row: Any) -> dict[str, Any]:
    cc = row.campaign_criterion
    s = cc.ad_schedule
    return {
        "campaign_id": str(row.campaign.id),
        "campaign_name": str(row.campaign.name),
        "criterion_id": str(cc.criterion_id),
        "resource_name": str(cc.resource_name),
        "day_of_week": _nome(s.day_of_week),
        "start_hour": int(s.start_hour),
        "start_minute": ENUM_MINUTO.get(_nome(s.start_minute), 0),
        "end_hour": int(s.end_hour),
        "end_minute": ENUM_MINUTO.get(_nome(s.end_minute), 0),
        "bid_modifier": float(cc.bid_modifier) if cc.bid_modifier else None,
        "status": _nome(cc.status),
    }


def campaign_budget_query(*, campaign_ids: list[str] | None) -> str:
    where = (
        f"campaign.id IN ({','.join(campaign_ids)})"
        if campaign_ids
        else "campaign.status != 'REMOVED'"
    )
    return f"""
        SELECT campaign.id, campaign.name, campaign.campaign_budget,
               campaign_budget.id, campaign_budget.explicitly_shared, campaign_budget.amount_micros
        FROM campaign
        WHERE {where}
    """.strip()


def parse_campaign_budget_row(row: Any) -> dict[str, Any]:
    return {
        "campaign_id": str(row.campaign.id),
        "campaign_name": str(row.campaign.name),
        "budget_resource_name": str(row.campaign.campaign_budget),
        "budget_id": str(row.campaign_budget.id),
        "explicitly_shared": bool(row.campaign_budget.explicitly_shared),
        "amount_brl": round(int(row.campaign_budget.amount_micros) / 1_000_000, 2),
    }


def campaigns_on_budgets_query(*, budget_resource_names: list[str]) -> str:
    return f"""
        SELECT campaign.id, campaign.name, campaign.campaign_budget, campaign.status
        FROM campaign
        WHERE campaign.campaign_budget IN {gaql_in_list(budget_resource_names)}
          AND campaign.status != 'REMOVED'
    """.strip()


def parse_campaign_on_budget_row(row: Any) -> dict[str, Any]:
    return {
        "campaign_id": str(row.campaign.id),
        "campaign_name": str(row.campaign.name),
        "budget_resource_name": str(row.campaign.campaign_budget),
        "status": _nome(row.campaign.status),
    }


def day_hour_metrics_query(*, campaign_ids: list[str], start: date, end: date) -> str:
    """Conjunta dia x hora sobre `campaign` — probada valida em 03/09 (spec §4.2)."""
    return f"""
        SELECT campaign.id, segments.day_of_week, segments.hour,
               metrics.cost_micros, metrics.conversions
        FROM campaign
        WHERE {gaql_date_clause(start, end)}
          AND campaign.id IN ({",".join(campaign_ids)})
    """.strip()


def parse_day_hour_row(row: Any) -> dict[str, Any]:
    return {
        "campaign_id": str(row.campaign.id),
        "day_of_week": _nome(row.segments.day_of_week),
        "hour": int(row.segments.hour),
        "cost_micros": int(row.metrics.cost_micros),
        "conversions": float(row.metrics.conversions),
    }
