"""GAQL builders for audit_goal_attribution tool (Sprint 3b.35).

2 queries paralelas:
- conversion_action: actions com category/origin/primary_for_goal/etc
- customer_conversion_goal: goals com biddable flag per (category, origin)

Tool wrapper invoca via asyncio.gather paralelo.
"""

from typing import Any


def build_conversion_action_query() -> str:
    """GAQL pra conversion_action com fields necessários (audit_goal_attribution).

    Filters: status = ENABLED (PAUSED/REMOVED não afetam Smart Bidding ativo).
    """
    return """
        SELECT
          conversion_action.id,
          conversion_action.name,
          conversion_action.category,
          conversion_action.origin,
          conversion_action.primary_for_goal,
          conversion_action.include_in_conversions_metric,
          conversion_action.status
        FROM conversion_action
        WHERE conversion_action.status = 'ENABLED'
    """.strip()


def build_customer_conversion_goal_query() -> str:
    """GAQL pra customer_conversion_goal (category, origin, biddable)."""
    return """
        SELECT
          customer_conversion_goal.category,
          customer_conversion_goal.origin,
          customer_conversion_goal.biddable
        FROM customer_conversion_goal
    """.strip()


def parse_conversion_action_row(row: Any) -> dict[str, Any]:
    """Parse conversion_action GAQL row → dict (boundary)."""
    ca = row.conversion_action
    return {
        "id": str(ca.id),
        "name": ca.name,
        "category": ca.category.name,
        "origin": ca.origin.name,
        "primary_for_goal": bool(ca.primary_for_goal),
        "include_in_conversions_metric": bool(ca.include_in_conversions_metric),
        "status": ca.status.name,
    }


def parse_customer_conversion_goal_row(row: Any) -> dict[str, Any]:
    """Parse customer_conversion_goal GAQL row → dict (boundary)."""
    ccg = row.customer_conversion_goal
    return {
        "category": ccg.category.name,
        "origin": ccg.origin.name,
        "biddable": bool(ccg.biddable),
    }
