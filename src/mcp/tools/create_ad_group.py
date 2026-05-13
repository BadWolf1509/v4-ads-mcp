"""Tool: create_ad_group - create 1-10 new ad_groups in existing campaigns.

Always-CONFIRM (creates sao sensitive per spec §7.1). Pre-flight validates
parent campaigns: existence, not REMOVED, channel type compatibility, and
F12-style bidding strategy check if cpc_bid_micros provided.

Default status: PAUSED (safe default — match V4 playbook setup → review →
activate flow). Newly-created ad_group has no keywords/ads yet.

Not idempotent — Google permits duplicate names. Calling twice with same
payload creates 2 ad_groups.
"""

from collections import Counter
from typing import Any

from src.db import connection
from src.google_ads.queries._common import (
    validate_parent_campaigns_for_ad_group_create,
)
from src.governance.blast_radius import classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "ad_groups": {
            "type": "array",
            "minItems": 1,
            "maxItems": 10,
            "items": {
                "type": "object",
                "properties": {
                    "campaign_id": {"type": "string", "pattern": "^[0-9]+$"},
                    "name": {"type": "string", "minLength": 1, "maxLength": 255},
                    "type": {
                        "type": "string",
                        "enum": ["SEARCH_STANDARD", "SHOPPING_PRODUCT_ADS"],
                        "default": "SEARCH_STANDARD",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["ENABLED", "PAUSED"],
                        "default": "PAUSED",
                    },
                    "cpc_bid_micros": {"type": "integer", "minimum": 1},
                },
                "required": ["campaign_id", "name"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["customer_id", "ad_groups"],
    "additionalProperties": False,
}


def _build_params_summary(ad_groups: list[dict[str, Any]]) -> dict[str, Any]:
    """Audit-safe summary: distribution counts only (no names)."""
    type_counts = Counter(ag.get("type", "SEARCH_STANDARD") for ag in ad_groups)
    status_counts = Counter(ag.get("status", "PAUSED") for ag in ad_groups)
    with_bid = sum(1 for ag in ad_groups if "cpc_bid_micros" in ag)
    unique_campaigns = len({ag["campaign_id"] for ag in ad_groups})
    return {
        "count": len(ad_groups),
        "type_distribution": dict(type_counts),
        "status_distribution": dict(status_counts),
        "with_custom_bid_count": with_bid,
        "unique_parent_campaigns": unique_campaigns,
    }


@register_tool(
    name="create_ad_group",
    description=(
        "Cria 1-10 novos ad_groups em campaigns existentes. Cada ad_group tem "
        "campaign_id (parent) + name (1-255 chars) + type opcional "
        "(SEARCH_STANDARD default | SHOPPING_PRODUCT_ADS) + status opcional "
        "(PAUSED default | ENABLED) + cpc_bid_micros opcional (so valido em "
        "campaigns MANUAL_CPC/ENHANCED_CPC). Sempre CONFIRM (creates sensitive "
        "per spec §7.1). Pre-flight rejeita campaign inexistente, REMOVED, ou "
        "channel/strategy incompativel. NAO idempotente — Google permite nomes "
        "duplicados. Apos criar, use add_keywords + add ads pra setup completo."
    ),
    input_schema=_SCHEMA,
)
async def create_ad_group(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    ad_groups = args["ad_groups"]
    target_count = len(ad_groups)

    error = await validate_parent_campaigns_for_ad_group_create(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        ad_groups=ad_groups,
    )
    if error:
        return {"status": "error", "error": error, "operation": "create_ad_group"}

    risk = classify(operation="create_ad_group", params={"target_count": target_count})

    params_summary = _build_params_summary(ad_groups)
    type_dist = params_summary["type_distribution"]
    status_dist = params_summary["status_distribution"]
    unique_camps = params_summary["unique_parent_campaigns"]
    summary = (
        f"Criar {target_count} ad_group(s) em {unique_camps} campaign(s). "
        f"Types: {', '.join(f'{t}({n})' for t, n in sorted(type_dist.items()))}. "
        f"Status inicial: {', '.join(f'{s}({n})' for s, n in sorted(status_dist.items()))}."
    )

    payload = {
        "ad_groups": ad_groups,
        "__target_count__": target_count,
        "__params_summary__": params_summary,
    }

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="create_ad_group",
            payload=payload,
            blast_summary=summary,
        )

    preview = [
        {
            "campaign_id": ag["campaign_id"],
            "name": ag["name"],
            "type": ag.get("type", "SEARCH_STANDARD"),
            "status": ag.get("status", "PAUSED"),
            **({"cpc_bid_micros": ag["cpc_bid_micros"]} if "cpc_bid_micros" in ag else {}),
        }
        for ag in ad_groups
    ]

    return {
        "status": "dry_run",
        "operation": "create_ad_group",
        "customer_id": customer_id,
        "blast_summary": summary,
        "ad_groups_preview": preview,
        "confirmation_token": token,
        "expires_in_minutes": 10,
        "to_apply": "Chame apply_change(confirmation_token=<token>) para aplicar.",
        "confirmation_reason": risk.reason,
    }
