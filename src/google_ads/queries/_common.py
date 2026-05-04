"""Shared helpers for GAQL query construction."""

from datetime import UTC, date, datetime, timedelta


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
