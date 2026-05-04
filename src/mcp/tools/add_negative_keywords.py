"""Tool: add_negative_keywords - add campaign-level negative keywords. Auto-applies."""

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
        "keywords": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "minLength": 1, "maxLength": 80},
                    "match_type": {
                        "type": "string",
                        "enum": ["EXACT", "PHRASE", "BROAD"],
                    },
                },
                "required": ["text", "match_type"],
                "additionalProperties": False,
            },
            "minItems": 1,
            "maxItems": 500,
        },
    },
    "required": ["customer_id", "campaign_id", "keywords"],
    "additionalProperties": False,
}


@register_tool(
    name="add_negative_keywords",
    description=(
        "Adiciona palavras-chave negativas em nivel de campanha. Sempre auto-aplica "
        "(negativas raramente quebram coisas - spec §7.1). Aceita ate 500 negativas "
        "por chamada com match_type EXACT, PHRASE ou BROAD."
    ),
    input_schema=_SCHEMA,
)
async def add_negative_keywords(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    campaign_id = args["campaign_id"]
    keywords = args["keywords"]
    target_count = len(keywords)

    risk = classify(
        operation="add_negative_keywords",
        params={"target_count": target_count},
    )

    payload = {
        "campaign_id": campaign_id,
        "keywords": keywords,
        "__target_count__": target_count,
    }
    summary = (
        f"Adicionar {target_count} negativa(s) na campanha {campaign_id}. "
        f"Match types: {sorted({k['match_type'] for k in keywords})}."
    )

    # add_negative_keywords always classifies as AUTO per blast_radius
    result = await run_mutation(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        operation_type="add_negative_keywords",
        payload=payload,
        target_count=target_count,
    )
    return {
        "status": "applied",
        "operation": "add_negative_keywords",
        "customer_id": customer_id,
        "campaign_id": campaign_id,
        "blast_summary": summary,
        "applied_count": result["applied_count"],
        "google_request_id": result["google_request_id"],
        "auto_applied_reason": risk.reason,
    }
