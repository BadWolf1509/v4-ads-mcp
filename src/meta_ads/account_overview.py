"""Pure module pra meta_get_account_overview tool (Sprint M.2b).

Zero IO. Date math + Graph response parsing + deltas + warnings.
"""

from datetime import date, datetime, timedelta
from typing import Any

# Conversion actions a totalizar (cross-platform pattern com Google)
CONVERSION_ACTION_TYPES = frozenset(
    {
        "purchase",
        "lead",
        "complete_registration",
        "offsite_conversion.fb_pixel_purchase",
        "offsite_conversion.fb_pixel_lead",
        "offsite_conversion.fb_pixel_complete_registration",
    }
)

_PRESET_DAYS: dict[str, int] = {
    "LAST_7_DAYS": 7,
    "LAST_14_DAYS": 14,
    "LAST_30_DAYS": 30,
    "LAST_90_DAYS": 90,
}


def resolve_meta_date_window(
    preset: str | None,
    start_date: str | None,
    end_date: str | None,
    today: date,
) -> tuple[date, date]:
    """Resolve preset OR (start, end) → (start, end) date tuple.

    Custom (start+end) overrides preset. Default LAST_7_DAYS se ambos None.
    Raises ValueError se inconsistent (apenas um de start/end fornecido).
    """
    if start_date and end_date:
        return (date.fromisoformat(start_date), date.fromisoformat(end_date))
    if start_date or end_date:
        raise ValueError("start_date e end_date devem ser fornecidos juntos")
    preset = preset or "LAST_7_DAYS"
    if preset == "TODAY":
        return (today, today)
    if preset == "YESTERDAY":
        y = today - timedelta(days=1)
        return (y, y)
    days = _PRESET_DAYS[preset]
    return (today - timedelta(days=days - 1), today)


def shift_to_previous_period(start: date, end: date) -> tuple[date, date]:
    """Calculate previous period of same length."""
    length = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=length - 1)
    return (prev_start, prev_end)


def parse_insights_response(data: dict[str, Any]) -> dict[str, float | int]:
    """Parse Graph /insights response → normalized metrics dict.

    Empty/missing/null fields → 0.
    """
    rows = data.get("data") or []
    if not rows:
        return _empty_metrics()
    row = rows[0]
    actions = _sum_actions(row.get("actions") or [], CONVERSION_ACTION_TYPES)
    action_values = _sum_actions(row.get("action_values") or [], CONVERSION_ACTION_TYPES)
    return {
        "spend": _to_float(row.get("spend")),
        "impressions": _to_int(row.get("impressions")),
        "clicks": _to_int(row.get("clicks")),
        "ctr": _to_float(row.get("ctr")),
        "cpc": _to_float(row.get("cpc")),
        "reach": _to_int(row.get("reach")),
        "frequency": _to_float(row.get("frequency")),
        "conversions": int(actions),
        "conversion_value": float(action_values),
        "purchase_roas": _extract_purchase_roas(row.get("purchase_roas") or []),
    }


def compute_deltas(
    current: dict[str, float | int], previous: dict[str, float | int]
) -> dict[str, float | None]:
    """Returns dict with `_pct` suffix per metric. None if previous=0."""
    out: dict[str, float | None] = {}
    for key in (
        "spend",
        "impressions",
        "clicks",
        "conversions",
        "conversion_value",
        "purchase_roas",
    ):
        prev_val = previous.get(key, 0)
        curr_val = current.get(key, 0)
        if prev_val == 0:
            out[f"{key}_pct"] = None
        else:
            pct = round((curr_val - prev_val) / prev_val * 100, 2)
            out[f"{key}_pct"] = pct
    return out


def build_warnings(
    account_status_label: str,
    token_expires_at: datetime | None,
    now: datetime,
) -> list[str]:
    """Returns lista PT-BR warnings ativos (account_status problema + token <7d)."""
    out: list[str] = []
    if account_status_label != "ATIVO":
        out.append(
            f"account_status={account_status_label} — "
            f"métricas podem estar desatualizadas ou ad serving suspenso. "
            f"Verificar billing/status no Meta Business Suite."
        )
    if token_expires_at is not None:
        days_left = (token_expires_at - now).days
        if days_left < 7:
            iso_date = token_expires_at.date().isoformat()
            out.append(
                f"Token OAuth Meta expira em {days_left} dias ({iso_date}). "
                f"Reconectar via /admin → 'Conectar Meta' pra evitar interrupção das tools."
            )
    return out


# ============================================================================
# Helpers (module-private)
# ============================================================================


def _sum_actions(actions: list[dict[str, Any]], filter_types: frozenset[str]) -> float:
    return sum(_to_float(a.get("value")) for a in actions if a.get("action_type") in filter_types)


def _extract_purchase_roas(roas_arr: list[dict[str, Any]]) -> float:
    for entry in roas_arr:
        if entry.get("action_type") in ("purchase", "omni_purchase"):
            return _to_float(entry.get("value"))
    return 0.0


def _to_float(v: Any) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _to_int(v: Any) -> int:
    if v is None:
        return 0
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _empty_metrics() -> dict[str, float | int]:
    return {
        "spend": 0.0,
        "impressions": 0,
        "clicks": 0,
        "ctr": 0.0,
        "cpc": 0.0,
        "reach": 0,
        "frequency": 0.0,
        "conversions": 0,
        "conversion_value": 0.0,
        "purchase_roas": 0.0,
    }
