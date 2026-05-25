"""Tool: apply_recommendation - apply a Google Ads recommendation. Auto-applies."""

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
            "description": (
                "Resource name completo da recomendacao "
                "(ex: 'customers/1234567890/recommendations/abc123'). "
                "Use get_recommendations pra listar as pendentes."
            ),
        },
    },
    "required": ["customer_id", "recommendation_resource_name"],
    "additionalProperties": False,
}


@register_tool(
    name="apply_recommendation",
    description=(
        "Aplica uma recomendacao pendente do Google Ads. Sempre auto-aplica "
        "(o Google ja avaliou o impacto). Use get_recommendations primeiro "
        "para listar as disponiveis."
    ),
    input_schema=_SCHEMA,
)
async def apply_recommendation(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    rec_resource = args["recommendation_resource_name"]

    risk = classify(operation="apply_recommendation", params={"target_count": 1})

    payload = {
        "recommendation_resource_name": rec_resource,
        "__target_count__": 1,
    }
    summary = f"Aplicar recomendacao {rec_resource} na conta {customer_id}."

    result = await run_recommendation_action(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        operation_type="apply_recommendation",
        payload=payload,
    )
    return {
        "status": "applied",
        "operation": "apply_recommendation",
        "customer_id": customer_id,
        "blast_summary": summary,
        "applied_count": result["applied_count"],
        "provider_request_id": result["provider_request_id"],
        "auto_applied_reason": risk.reason,
    }
