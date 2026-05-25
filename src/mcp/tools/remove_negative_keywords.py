# bucket: defer
"""Tool: remove_negative_keywords - remove campaign-level negative keywords. Auto-applies."""

from typing import Any

from src.google_ads.mutations import run_mutation
from src.governance.blast_radius import classify
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "campaign_id": {"type": "string", "pattern": "^[0-9]+$"},
        "criterion_ids": {
            "type": "array",
            "items": {"type": "string", "pattern": "^[0-9]+$"},
            "minItems": 1,
            "maxItems": 500,
        },
    },
    "required": ["customer_id", "campaign_id", "criterion_ids"],
    "additionalProperties": False,
}


@register_tool(
    name="remove_negative_keywords",
    description=(
        "[DEFER] Remove palavras-chave negativas em nivel de campanha. Sempre auto-aplica "
        "(negativas raramente quebram coisas - spec §7.1). Aceita ate 500 remocoes "
        "por chamada via criterion_id."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def remove_negative_keywords(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    campaign_id = args["campaign_id"]
    criterion_ids = args["criterion_ids"]
    target_count = len(criterion_ids)

    risk = classify(
        operation="remove_negative_keywords",
        params={"target_count": target_count},
    )

    payload = {
        "campaign_id": campaign_id,
        "criterion_ids": criterion_ids,
        "__target_count__": target_count,
    }
    summary = f"Remover {target_count} negativa(s) da campanha {campaign_id}."

    result = await run_mutation(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        operation_type="remove_negative_keywords",
        payload=payload,
        target_count=target_count,
    )
    return {
        "status": "applied",
        "operation": "remove_negative_keywords",
        "customer_id": customer_id,
        "campaign_id": campaign_id,
        "blast_summary": summary,
        "applied_count": result["applied_count"],
        "provider_request_id": result["provider_request_id"],
        "auto_applied_reason": risk.reason,
    }
