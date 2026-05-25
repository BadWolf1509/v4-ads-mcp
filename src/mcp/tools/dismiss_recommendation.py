# bucket: defer
"""Tool: dismiss_recommendation - dismiss a Google Ads recommendation. Auto-applies."""

from typing import Any

from src.google_ads.mutations import run_recommendation_action
from src.governance.blast_radius import classify
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "recommendation_resource_name": {
            "type": "string",
            "minLength": 10,
        },
    },
    "required": ["customer_id", "recommendation_resource_name"],
    "additionalProperties": False,
}


@register_tool(
    name="dismiss_recommendation",
    description=(
        "[DEFER] Dispensa (rejeita) uma recomendacao pendente do Google Ads. Auto-aplica."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def dismiss_recommendation(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    rec_resource = args["recommendation_resource_name"]

    risk = classify(operation="dismiss_recommendation", params={"target_count": 1})

    payload = {
        "recommendation_resource_name": rec_resource,
        "__target_count__": 1,
    }
    summary = f"Dispensar recomendacao {rec_resource} na conta {customer_id}."

    result = await run_recommendation_action(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        operation_type="dismiss_recommendation",
        payload=payload,
    )
    return {
        "status": "applied",
        "operation": "dismiss_recommendation",
        "customer_id": customer_id,
        "blast_summary": summary,
        "applied_count": result["applied_count"],
        "provider_request_id": result["provider_request_id"],
        "auto_applied_reason": risk.reason,
    }
