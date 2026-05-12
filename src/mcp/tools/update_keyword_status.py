"""Tool: update_keyword_status - pause/enable/remove keywords."""

from typing import Any

from src.db import connection
from src.google_ads.mutations import run_mutation
from src.governance.blast_radius import RiskLevel, classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "keywords": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ad_group_id": {"type": "string", "pattern": "^[0-9]+$"},
                    "criterion_id": {"type": "string", "pattern": "^[0-9]+$"},
                },
                "required": ["ad_group_id", "criterion_id"],
                "additionalProperties": False,
            },
            "minItems": 1,
        },
        "new_status": {
            "type": "string",
            "enum": ["ENABLED", "PAUSED", "REMOVED"],
        },
    },
    "required": ["customer_id", "keywords", "new_status"],
    "additionalProperties": False,
}


@register_tool(
    name="update_keyword_status",
    description=(
        "Pausa, ativa ou remove uma ou mais palavras-chave. Cada keyword e "
        "identificada por (ad_group_id, criterion_id). Ate 5 keywords auto-aplica; "
        ">5 retorna preview com confirmation_token."
    ),
    input_schema=_SCHEMA,
)
async def update_keyword_status(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    keywords = args["keywords"]
    new_status = args["new_status"]
    target_count = len(keywords)

    risk = classify(
        operation="update_keyword_status",
        params={"target_count": target_count, "new_status": new_status},
    )
    payload = {
        "keywords": keywords,
        "new_status": new_status,
        "__target_count__": target_count,
    }
    summary = f"Mudar status de {target_count} palavra(s)-chave para {new_status}."

    if risk.level == RiskLevel.AUTO:
        result = await run_mutation(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="update_keyword_status",
            payload=payload,
            target_count=target_count,
        )
        return {
            "status": "applied",
            "operation": "update_keyword_status",
            "customer_id": customer_id,
            "blast_summary": summary,
            "applied_count": result["applied_count"],
            "google_request_id": result["google_request_id"],
            "auto_applied_reason": risk.reason,
        }

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="update_keyword_status",
            payload=payload,
            blast_summary=summary,
        )
    return {
        "status": "dry_run",
        "operation": "update_keyword_status",
        "customer_id": customer_id,
        "blast_summary": summary,
        "confirmation_token": token,
        "expires_in_minutes": 10,
        "to_apply": "Chame apply_change(confirmation_token=<token>) para aplicar.",
        "confirmation_reason": risk.reason,
    }
