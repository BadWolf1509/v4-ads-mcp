"""Tool: get_change_history - audit-log of recent changes to the account.

Wraps the change_event GAQL resource with structured filters and a summary
block. Two V4 skills (auditoria-google-ads + analise-performance-google-ads)
call this as 'CRITICO antes de tudo' to detect:
- Auto-apply Recommendations (client_type=GOOGLE_ADS_RECOMMENDATIONS_AUTO_APPLY)
- Structural changes (geo settings, conversion actions, bidding strategy)
- Who changed what

Audited as a sensitive read.
"""

from collections import Counter
from typing import Any
from uuid import UUID

from src.google_ads.queries._common import parse_date_range
from src.google_ads.queries.change_history import change_history_query
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_RESOURCE_TYPES = [
    "CAMPAIGN",
    "AD_GROUP",
    "AD_GROUP_CRITERION",
    "AD_GROUP_AD",
    "CAMPAIGN_CRITERION",
    "CAMPAIGN_BUDGET",
    "BIDDING_STRATEGY",
    "CONVERSION_ACTION",
    "CUSTOMER_NEGATIVE_CRITERION",
    "ASSET",
    "CAMPAIGN_ASSET",
    "AD_GROUP_ASSET",
]

_CLIENT_TYPES = [
    "GOOGLE_ADS_UI",
    "GOOGLE_ADS_API",
    "GOOGLE_ADS_RECOMMENDATIONS_AUTO_APPLY",
    "GOOGLE_ADS_AUTOMATED_RULES",
    "GOOGLE_ADS_BULK_UPLOAD",
    "GOOGLE_ADS_EDITOR",
    "GOOGLE_ADS_MOBILE_APP",
    "GOOGLE_ADS_SCRIPTS",
    "GOOGLE_ADS_WEB_SERVICES",
    "OTHER",
]

_AUTO_APPLY_CLIENT_TYPE = "GOOGLE_ADS_RECOMMENDATIONS_AUTO_APPLY"

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "date_range": {"default": "LAST_7_DAYS"},
        "resource_types": {
            "type": "array",
            "items": {"type": "string", "enum": _RESOURCE_TYPES},
        },
        "operation_types": {
            "type": "array",
            "items": {"type": "string", "enum": ["CREATE", "UPDATE", "REMOVE"]},
        },
        "user_emails": {
            "type": "array",
            "items": {"type": "string", "format": "email"},
        },
        "client_types": {
            "type": "array",
            "items": {"type": "string", "enum": _CLIENT_TYPES},
        },
        "limit": {"type": "integer", "minimum": 1, "maximum": 10000, "default": 200},
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


def _parse_resource_path(path: str) -> tuple[str | None, str | None]:
    """Parse 'customers/123/campaigns/456' -> ('campaign', '456').

    Returns (None, None) if path is unrecognized.
    """
    parts = path.split("/")
    # path is "customers/{cid}/{resource_plural}/{id}[...]"
    if len(parts) < 4 or parts[0] != "customers":
        return None, None
    resource_plural = parts[2]
    # Common resource names — singular form for the return
    plural_to_type = {
        "campaigns": "campaign",
        "adGroups": "ad_group",
        "adGroupAds": "ad_group_ad",
        "adGroupCriteria": "ad_group_criterion",
        "campaignCriteria": "campaign_criterion",
        "campaignBudgets": "campaign_budget",
        "biddingStrategies": "bidding_strategy",
        "conversionActions": "conversion_action",
        "customerNegativeCriteria": "customer_negative_criterion",
        "assets": "asset",
        "campaignAssets": "campaign_asset",
        "adGroupAssets": "ad_group_asset",
    }
    return plural_to_type.get(resource_plural), parts[3] if len(parts) > 3 else None


def _row_formatter(row: Any) -> dict[str, Any]:
    ce = row.change_event
    resource_path = str(ce.change_resource_name)
    _rtype, rid = _parse_resource_path(resource_path)
    # changed_fields is a FieldMask (paths joined by '.'); split into list
    changed = list(ce.changed_fields.paths) if hasattr(ce.changed_fields, "paths") else []

    # campaign / ad_group references on change_event are resource paths; convert
    campaign_path = str(ce.campaign) if ce.campaign else ""
    ad_group_path = str(ce.ad_group) if ce.ad_group else ""
    _, campaign_id = _parse_resource_path(campaign_path) if campaign_path else (None, None)
    _, ad_group_id = _parse_resource_path(ad_group_path) if ad_group_path else (None, None)

    op_enum = ce.resource_change_operation
    op_str = op_enum.name if hasattr(op_enum, "name") else str(op_enum)
    rtype_enum = ce.change_resource_type
    rtype_str = rtype_enum.name if hasattr(rtype_enum, "name") else str(rtype_enum)
    ct_enum = ce.client_type
    ct_str = ct_enum.name if hasattr(ct_enum, "name") else str(ct_enum)

    return {
        "change_date_time": str(ce.change_date_time),
        "user_email": str(ce.user_email),
        "client_type": ct_str,
        "resource_type": rtype_str,
        "resource_id": rid or "",
        "resource_name": "",  # filled in by _resolve_names after the fact
        "_resource_path": resource_path,  # internal, removed before returning
        "operation": op_str,
        "changed_fields": changed,
        "campaign_id": campaign_id,
        "ad_group_id": ad_group_id,
    }


def _build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate counts. Auto-apply rows collapse into synthetic 'auto-apply' user bucket."""
    by_user: Counter[str] = Counter()
    by_resource_type: Counter[str] = Counter()
    by_operation: Counter[str] = Counter()
    auto_applied = 0
    for r in rows:
        if r["client_type"] == _AUTO_APPLY_CLIENT_TYPE:
            by_user["auto-apply"] += 1
            auto_applied += 1
        else:
            by_user[r["user_email"]] += 1
        by_resource_type[r["resource_type"]] += 1
        by_operation[r["operation"]] += 1

    return {
        "total_changes": len(rows),
        "by_user": dict(by_user),
        "by_resource_type": dict(by_resource_type),
        "by_operation": dict(by_operation),
        "auto_applied_count": auto_applied,
    }


async def _resolve_names(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    rows: list[dict[str, Any]],
) -> dict[tuple[str, str], str]:
    """Resolve (resource_type, resource_id) -> human name via 0-2 follow-up queries."""
    name_map: dict[tuple[str, str], str] = {}

    campaign_ids = sorted({r["campaign_id"] for r in rows if r["campaign_id"]})
    ad_group_ids = sorted({r["ad_group_id"] for r in rows if r["ad_group_id"]})

    if campaign_ids:
        ids_clause = ",".join(campaign_ids)
        q = f"SELECT campaign.id, campaign.name FROM campaign WHERE campaign.id IN ({ids_clause})"
        rows_c = await run_report(
            manager_id=manager_id,
            session_id=session_id,
            customer_id=customer_id,
            query=q,
            row_formatter=lambda r: {"id": str(r.campaign.id), "name": str(r.campaign.name)},
            operation_name="get_change_history_resolve_campaigns",
            audit_this_call=False,
        )
        for c in rows_c:
            name_map[("campaign", c["id"])] = c["name"]

    if ad_group_ids:
        ids_clause = ",".join(ad_group_ids)
        q = f"SELECT ad_group.id, ad_group.name FROM ad_group WHERE ad_group.id IN ({ids_clause})"
        rows_a = await run_report(
            manager_id=manager_id,
            session_id=session_id,
            customer_id=customer_id,
            query=q,
            row_formatter=lambda r: {"id": str(r.ad_group.id), "name": str(r.ad_group.name)},
            operation_name="get_change_history_resolve_ad_groups",
            audit_this_call=False,
        )
        for a in rows_a:
            name_map[("ad_group", a["id"])] = a["name"]

    return name_map


@register_tool(
    name="get_change_history",
    description=(
        "Historico de mudancas (change_event) na conta nos ultimos 7-30 dias com "
        "filtros opcionais (resource_types, operation_types, user_emails, "
        "client_types). Util pra auditoria 'CRITICO antes de tudo': detectar "
        "auto-apply Recommendations, mudancas estruturais, e quem mexeu no que. "
        "Inclui bloco summary com totais por usuario/resource/operation e contagem "
        "de auto-apply. Janela maxima 30 dias (limite da API). Audited como read "
        "sensivel."
    ),
    input_schema=_SCHEMA,
)
async def get_change_history(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    start, end = parse_date_range(args.get("date_range", "LAST_7_DAYS"))
    limit = args.get("limit", 200)

    query = change_history_query(
        start=start,
        end=end,
        resource_types=args.get("resource_types"),
        operation_types=args.get("operation_types"),
        user_emails=args.get("user_emails"),
        client_types=args.get("client_types"),
        limit=limit,
    )

    rows = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_row_formatter,
        operation_name="get_change_history",
        audit_this_call=True,
    )

    # Resolve campaign/ad_group names (0-2 extra ops)
    name_map = await _resolve_names(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        rows=rows,
    )
    for r in rows:
        # Prefer the resource_id's own resource_type lookup; fall back to campaign_id
        key = (r["resource_type"].lower(), r["resource_id"])
        if key in name_map:
            r["resource_name"] = name_map[key]
        elif r["campaign_id"]:
            r["resource_name"] = name_map.get(
                ("campaign", r["campaign_id"]), r.pop("_resource_path")
            )
        else:
            r["resource_name"] = r.pop("_resource_path")
        r.pop("_resource_path", None)

    summary = _build_summary(rows)

    return {
        "customer_id": customer_id,
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "rows": rows,
        "summary": summary,
    }
