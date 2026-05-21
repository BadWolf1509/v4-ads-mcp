"""GAQL builder for audit_orphan_smart_actions tool (Sprint 3b.37).

Single query sobre conversion_action com:
- Date range filter (gaql_date_clause helper) — segments.date
- status=ENABLED hardcoded server-side
- Optional category filter
- 6 fields + metrics.all_conversions SELECT
"""

from datetime import date
from typing import Any

from src.google_ads.flag_orphan_smart_actions import ConversionActionRow
from src.google_ads.queries._common import gaql_date_clause


def build_audit_orphan_smart_actions_query(
    *,
    start_date: str,
    end_date: str,
    category: str | None,
) -> str:
    """GAQL pra conversion_action com metrics aggregadas em window.

    Filters: date range via gaql_date_clause + status=ENABLED + optional category.
    Returns one row per conversion_action with metrics aggregated over date window.
    """
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    date_clause = gaql_date_clause(start, end)

    category_clause = ""
    if category:
        category_clause = f" AND conversion_action.category = '{category}'"

    return f"""
        SELECT
          conversion_action.id,
          conversion_action.name,
          conversion_action.category,
          conversion_action.origin,
          conversion_action.primary_for_goal,
          conversion_action.status,
          metrics.all_conversions
        FROM conversion_action
        WHERE {date_clause}
          AND conversion_action.status = 'ENABLED'{category_clause}
    """.strip()


def parse_conversion_action_row(row: Any) -> dict[str, Any]:
    """Parse conversion_action GAQL row → dict (boundary).

    Uses `.name` on category/origin/status enums (Sprint 3b.7 lesson:
    proto-plus v20+ regression — `str(enum)` retorna integer, `.name`
    retorna 'CONTACT'/'WEBSITE'/'ENABLED').
    """
    ca = row.conversion_action
    return {
        "conversion_action_id": str(ca.id),
        "name": ca.name,
        "category": ca.category.name,
        "origin": ca.origin.name,
        "primary_for_goal": bool(ca.primary_for_goal),
        "status": ca.status.name,
        "all_conversions": float(row.metrics.all_conversions),
    }


def dict_to_conversion_action_row(d: dict[str, Any]) -> ConversionActionRow:
    """Convert conversion_action row dict to ConversionActionRow dataclass (defensive)."""
    return ConversionActionRow(
        conversion_action_id=str(d.get("conversion_action_id", "")),
        name=str(d.get("name", "")),
        category=str(d.get("category", "")),
        origin=str(d.get("origin", "")),
        primary_for_goal=bool(d.get("primary_for_goal", False)),
        status=str(d.get("status", "")),
        all_conversions=float(d.get("all_conversions", 0.0)),
    )
