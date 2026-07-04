# bucket: defer
"""Tool: update_campaign_bidding - change a campaign's bidding strategy. Always confirms."""

from typing import Any

from src.db import connection
from src.governance.blast_radius import classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._mutate_common import error_envelope, preview_envelope
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "campaign_id": {"type": "string", "pattern": "^[0-9]+$"},
        "strategy": {
            "type": "string",
            "enum": ["TARGET_CPA", "TARGET_ROAS", "MAXIMIZE_CONVERSIONS"],
        },
        "target_cpa_brl": {
            "type": "number",
            "exclusiveMinimum": 0,
            "description": "Target CPA em BRL (apenas para TARGET_CPA ou MAXIMIZE_CONVERSIONS).",
        },
        "target_roas": {
            "type": "number",
            "exclusiveMinimum": 0,
            "description": "Target ROAS (apenas para TARGET_ROAS, ex: 4.0 = 400%).",
        },
    },
    "required": ["customer_id", "campaign_id", "strategy"],
    "additionalProperties": False,
}


@register_tool(
    name="update_campaign_bidding",
    description=(
        "[DEFER] Muda a estrategia de bidding de uma campanha (TARGET_CPA, TARGET_ROAS, "
        "MAXIMIZE_CONVERSIONS). Sempre exige confirmacao via apply_change."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def update_campaign_bidding(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    campaign_id = args["campaign_id"]
    strategy = args["strategy"]

    # Build payload + summary based on strategy
    payload: dict[str, Any] = {
        "campaign_id": campaign_id,
        "strategy": strategy,
        "__target_count__": 1,
    }

    summary_parts = [f"Mudar bidding da campanha {campaign_id} para {strategy}"]
    if strategy in ("TARGET_CPA", "MAXIMIZE_CONVERSIONS"):
        if "target_cpa_brl" not in args:
            return error_envelope(
                "update_campaign_bidding",
                f"target_cpa_brl e obrigatorio para a estrategia {strategy}.",
                customer_id=customer_id,
            )
        target_brl = float(args["target_cpa_brl"])
        payload["target_value_micros"] = int(target_brl * 1_000_000)
        summary_parts.append(f"com Target CPA R$ {target_brl:.2f}")
    elif strategy == "TARGET_ROAS":
        if "target_roas" not in args:
            return error_envelope(
                "update_campaign_bidding",
                "target_roas e obrigatorio para a estrategia TARGET_ROAS.",
                customer_id=customer_id,
            )
        target_roas = float(args["target_roas"])
        payload["target_roas"] = target_roas
        summary_parts.append(f"com Target ROAS {target_roas:.2f}")

    summary = " ".join(summary_parts) + "."

    risk = classify(
        operation="update_campaign_bidding",
        params={"target_count": 1},
    )

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="update_campaign_bidding",
            payload=payload,
            blast_summary=summary,
        )
    return preview_envelope(
        "update_campaign_bidding",
        customer_id,
        summary,
        token,
        confirmation_reason=risk.reason,
    )
