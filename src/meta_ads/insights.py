# bucket: always
"""Shared insights helpers for meta_get_*_performance tools (Sprint M.3 + M.3.1 hotfix).

Pure module — zero SDK imports, fully unit-testable.

Reusa META_EFFECTIVE_STATUS_LABELS de src.mcp.tools._meta_common.

M.3.1 hotfix (F53): `effective_status` removed from fields lists + filtering
block — Meta Insights API rejects it (it's Campaign/AdSet/Ad metadata, not
an Insights metric field). V0 returns all entities regardless of status;
V1 enhancement = 2-step query (fetch /campaigns?fields=effective_status,
then /insights?filtering=[campaign_id IN <ids>]). Parser preserves defensive
fallback `effective_status="UNKNOWN"` for backwards compat with response shape.
"""

from datetime import date
from typing import Any, Literal

from src.mcp.tools._meta_common import META_EFFECTIVE_STATUS_LABELS

Level = Literal["campaign", "adset", "ad"]

# Per-level field lists (Meta Insights API field names)
_COMMON_INSIGHTS_FIELDS = [
    "spend",
    "impressions",
    "clicks",
    "ctr",
    "cpc",
    "reach",
    "frequency",
    "actions",
    "action_values",
    "purchase_roas",
]
# M.3.1: effective_status removed (F53). M.3.1.1 iteration 2 (F54):
# billing_event + daily_budget (adset) + creative_id (ad) also rejected by
# Meta Insights API empirically. Kept: objective (campaign), optimization_goal
# (adset) — both empirically validated in iteration 1.
# V1 enhancement: enrich via 2-step query (/adsets + /ads endpoints).
INSIGHTS_FIELDS_CAMPAIGN = [
    "campaign_id",
    "campaign_name",
    "objective",
    *_COMMON_INSIGHTS_FIELDS,
]
INSIGHTS_FIELDS_ADSET = [
    "adset_id",
    "adset_name",
    "campaign_id",
    "campaign_name",
    "optimization_goal",
    *_COMMON_INSIGHTS_FIELDS,
]
INSIGHTS_FIELDS_AD = [
    "ad_id",
    "ad_name",
    "adset_id",
    "adset_name",
    "campaign_id",
    "campaign_name",
    *_COMMON_INSIGHTS_FIELDS,
]


def build_insights_call(
    *,
    level: Level,
    ad_account_id: str,
    start: date,
    end: date,
    limit: int,
) -> tuple[str, dict[str, Any]]:
    """Build Graph API edge path + params dict for a /insights call.

    Returns: (edge, params) — caller passes both to run_meta_graph_get.

    M.3.1 hotfix (F53): effective_status param removed from signature.
    Filtering block omitted — Meta Insights API rejects `effective_status` as
    filter field. V1 enhancement = 2-step query pra restore filter capability.
    """
    fields_by_level = {
        "campaign": INSIGHTS_FIELDS_CAMPAIGN,
        "adset": INSIGHTS_FIELDS_ADSET,
        "ad": INSIGHTS_FIELDS_AD,
    }
    edge = f"/{ad_account_id}/insights"
    params: dict[str, Any] = {
        "level": level,
        "fields": ",".join(fields_by_level[level]),
        "time_range": f'{{"since":"{start.isoformat()}","until":"{end.isoformat()}"}}',
        "limit": limit,
        "ad_account_id": ad_account_id,  # passed thru for BUC counter key
    }
    return edge, params


def _extract_action_value(actions: list[dict[str, Any]] | None, action_type: str) -> float:
    """Extract value of FIRST action matching action_type. 0 if absent."""
    if not actions:
        return 0.0
    for a in actions:
        if a.get("action_type") == action_type:
            try:
                return float(a.get("value", 0))
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _extract_purchase_roas(roas_list: list[dict[str, Any]] | None) -> float:
    """purchase_roas é lista: [{'action_type':'omni_purchase','value':'4.45'}]."""
    if not roas_list:
        return 0.0
    try:
        return float(roas_list[0].get("value", 0))
    except (TypeError, ValueError, IndexError):
        return 0.0


def parse_insights_row(row: dict[str, Any], level: Level) -> dict[str, Any]:
    """Parse single Meta Insights row → flat dict for MCP response.

    Level-specific fields prepended (id/name/objective/etc).
    Common metrics + extracted actions follow.
    """
    spend = float(row.get("spend") or 0)
    clicks = int(row.get("clicks") or 0)
    actions = row.get("actions")
    action_values = row.get("action_values")

    effective_status_raw = row.get("effective_status", "UNKNOWN")
    common: dict[str, Any] = {
        "effective_status": effective_status_raw,
        "effective_status_label": META_EFFECTIVE_STATUS_LABELS.get(
            effective_status_raw, "DESCONHECIDO"
        ),
        "spend_brl": round(spend, 2),
        "impressions": int(row.get("impressions") or 0),
        "clicks": clicks,
        "ctr": round(float(row.get("ctr") or 0) / 100, 4),  # Meta % → decimal
        "cpc_brl": round(float(row.get("cpc") or 0), 4),
        "reach": int(row.get("reach") or 0),
        "frequency": round(float(row.get("frequency") or 0), 2),
        "purchases": int(_extract_action_value(actions, "purchase")),
        "purchases_value_brl": round(_extract_action_value(action_values, "purchase"), 2),
        "purchase_roas": _extract_purchase_roas(row.get("purchase_roas")),
        "leads": int(_extract_action_value(actions, "lead")),
    }

    if level == "campaign":
        return {
            "campaign_id": row.get("campaign_id"),
            "campaign_name": row.get("campaign_name"),
            "objective": row.get("objective"),
            **common,
        }
    if level == "adset":
        daily_budget_raw = row.get("daily_budget")
        daily_budget_brl = round(float(daily_budget_raw) / 100, 2) if daily_budget_raw else None
        return {
            "ad_set_id": row.get("adset_id"),
            "ad_set_name": row.get("adset_name"),
            "campaign_id": row.get("campaign_id"),
            "campaign_name": row.get("campaign_name"),
            "optimization_goal": row.get("optimization_goal"),
            "billing_event": row.get("billing_event"),
            "daily_budget_brl": daily_budget_brl,
            **common,
        }
    # ad
    return {
        "ad_id": row.get("ad_id"),
        "ad_name": row.get("ad_name"),
        "ad_set_id": row.get("adset_id"),
        "ad_set_name": row.get("adset_name"),
        "campaign_id": row.get("campaign_id"),
        "campaign_name": row.get("campaign_name"),
        "creative_id": row.get("creative_id"),
        **common,
    }
