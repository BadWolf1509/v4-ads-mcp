"""Shared helpers for GAQL query construction."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from src.google_ads.reports import run_report


class InvalidDateRangeError(ValueError):
    """Raised when a date range cannot be parsed."""


_PRESETS = {
    "TODAY",
    "YESTERDAY",
    "LAST_7_DAYS",
    "LAST_14_DAYS",
    "LAST_30_DAYS",
    "LAST_90_DAYS",
    "THIS_MONTH",
    "LAST_MONTH",
    "THIS_WEEK",
    "LAST_WEEK",
}


def _today() -> date:
    return datetime.now(UTC).date()


def _yesterday() -> date:
    return _today() - timedelta(days=1)


def parse_date_range(arg: str | dict[str, str]) -> tuple[date, date]:
    """Resolve a date_range param into (start_date, end_date) inclusive.

    Accepts either a preset string (e.g., 'LAST_7_DAYS') or an explicit
    dict {from: ISO_DATE, to: ISO_DATE}.
    """
    if isinstance(arg, dict):
        try:
            start = date.fromisoformat(arg["from"])
            end = date.fromisoformat(arg["to"])
        except (KeyError, ValueError) as e:
            raise InvalidDateRangeError(f"Invalid date dict {arg}: {e}") from e
        if start > end:
            raise InvalidDateRangeError(f"date_range from ({start}) is after to ({end})")
        return start, end

    if not isinstance(arg, str):
        raise InvalidDateRangeError(f"date_range must be string or dict, got {type(arg)}")

    preset = arg.upper()
    if preset not in _PRESETS:
        raise InvalidDateRangeError(
            f"Unknown date_range preset '{preset}'. Valid presets: {', '.join(sorted(_PRESETS))}"
        )

    today = _today()
    yesterday = _yesterday()

    if preset == "TODAY":
        return today, today
    if preset == "YESTERDAY":
        return yesterday, yesterday
    if preset == "LAST_7_DAYS":
        return yesterday - timedelta(days=6), yesterday
    if preset == "LAST_14_DAYS":
        return yesterday - timedelta(days=13), yesterday
    if preset == "LAST_30_DAYS":
        return yesterday - timedelta(days=29), yesterday
    if preset == "LAST_90_DAYS":
        return yesterday - timedelta(days=89), yesterday
    if preset == "THIS_MONTH":
        return today.replace(day=1), yesterday
    if preset == "LAST_MONTH":
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        first_prev = last_prev.replace(day=1)
        return first_prev, last_prev
    if preset == "THIS_WEEK":
        # ISO week starts Monday; today.weekday() = 0 for Monday
        monday = today - timedelta(days=today.weekday())
        return monday, yesterday if yesterday >= monday else monday
    if preset == "LAST_WEEK":
        last_sunday = today - timedelta(days=today.weekday() + 1)
        last_monday = last_sunday - timedelta(days=6)
        return last_monday, last_sunday

    raise InvalidDateRangeError(f"Unhandled preset {preset}")  # unreachable


def get_comparison_range(start: date, end: date) -> tuple[date, date]:
    """Given a date range, return the immediately-previous period of equal length.

    Example: for [2026-04-08, 2026-04-14] (7 days), returns [2026-04-01, 2026-04-07].
    """
    period_days = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=period_days - 1)
    return prev_start, prev_end


def gaql_date_clause(start: date, end: date) -> str:
    """Format a GAQL `segments.date BETWEEN '...' AND '...'` clause."""
    return f"segments.date BETWEEN '{start.isoformat()}' AND '{end.isoformat()}'"


# Common metric SELECT fragments — reuse across many tools
METRIC_FIELDS = {
    "impressions": "metrics.impressions",
    "clicks": "metrics.clicks",
    "cost_micros": "metrics.cost_micros",
    "conversions": "metrics.conversions",
    "conversions_value": "metrics.conversions_value",
    "ctr": "metrics.ctr",
    "average_cpc": "metrics.average_cpc",
    "cost_per_conversion": "metrics.cost_per_conversion",
    "value_per_conversion": "metrics.value_per_conversion",
}


def micros_to_currency(micros: int | float) -> float:
    """Google Ads stores money in micros (millionths). 1_500_000 micros = R$ 1.50."""
    return round(micros / 1_000_000.0, 2)


def value_proxy_warning(conversions: float, conversions_value: float) -> str | None:
    """Returns warning string PT-BR if conversions_value == conversions (1:1 placeholder
    tracking), else None.

    Real revenue tracking would have value != count (unless every conversion is
    coincidentally R$ 1.00 — extremely unlikely). 1:1 ratio strong signals that
    conversion action uses default value=1.0 BRL placeholder, making ROAS misleading.

    Sprint 3b.7 (P1b dogfood UX-1 finding).
    """
    if conversions > 0 and conversions == conversions_value:
        return (
            "conversions_value == conversions (1:1 ratio). Tracking provavelmente "
            "sem revenue real — ROAS pode ser misleading."
        )
    return None


async def validate_manual_cpc_strategy(
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    ad_group_ids: list[str],
) -> str | None:
    """Returns PT-BR error string if any ad_group is in non-MANUAL_CPC/ENHANCED_CPC
    campaign; else None.

    Performs 1 GAQL batch lookup. Whitelist {MANUAL_CPC, ENHANCED_CPC} matches
    strategies que honram cpc_bid_micros field (Google Ads API v23 docs:
    https://developers.google.com/google-ads/api/docs/campaigns/bidding/override-strategies).

    Sprint 3b.8 (P3 dogfood F12 finding — silent-acceptance bug family 6th variant).
    """
    if not ad_group_ids:
        return None

    ids_clause = ", ".join(ad_group_ids)
    query = (
        f"SELECT ad_group.id, campaign.id, campaign.name, "
        f"campaign.bidding_strategy_type "
        f"FROM ad_group WHERE ad_group.id IN ({ids_clause})"
    )

    def _format(row: Any) -> dict[str, str]:
        return {
            "ad_group_id": str(row.ad_group.id),
            "campaign_id": str(row.campaign.id),
            "campaign_name": row.campaign.name,
            "strategy": row.campaign.bidding_strategy_type.name,
        }

    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_format,
        operation_name="validate_manual_cpc_strategy",
    )

    whitelist = {"MANUAL_CPC", "ENHANCED_CPC"}
    for r in rows:
        if r["strategy"] not in whitelist:
            return (
                f"Campaign '{r['campaign_name']}' (id {r['campaign_id']}) usa "
                f"bidding_strategy_type '{r['strategy']}'. Manual CPC bids sao "
                f"ignorados nesta estrategia (Google API silent-failure). Mude "
                f"para MANUAL_CPC via update_campaign_bidding, ou ajuste budget/"
                f"targeting via outras tools."
            )
    return None
