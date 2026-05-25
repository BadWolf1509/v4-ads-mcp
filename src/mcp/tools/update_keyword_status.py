# bucket: always
"""Tool: update_keyword_status - pause/enable/remove keywords."""

from typing import Any

from src.db import connection
from src.google_ads.mutations import run_mutation
from src.google_ads.queries._common import validate_keyword_criterion_types
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
            "enum": ["ENABLED", "PAUSED"],
        },
    },
    "required": ["customer_id", "keywords", "new_status"],
    "additionalProperties": False,
}


@register_tool(
    name="update_keyword_status",
    description=(
        "[CORE] Pausa ou ativa uma ou mais palavras-chave. Cada keyword e identificada por "
        "(ad_group_id, criterion_id). Ate 5 keywords auto-aplica; >5 retorna preview "
        "com confirmation_token. Para REMOVER keywords, use Google Ads UI (tool dedicada "
        "`remove_keyword` pode ser adicionada em sprint futura se demanda real surgir)."
    ),
    input_schema=_SCHEMA,
    bucket="always",
)
async def update_keyword_status(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    keywords = args["keywords"]
    new_status = args["new_status"]
    target_count = len(keywords)

    # Sprint 3b.27 fix B1/F43: pre-flight async — Google API rejects negative
    # ad_group_criterion updates with generic error that doesn't identify which
    # IDs were problematic. Splits batch into positive vs negative.
    keyword_pairs = [(k["ad_group_id"], k["criterion_id"]) for k in keywords]
    preflight_error = await validate_keyword_criterion_types(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        keyword_pairs=keyword_pairs,
    )
    if preflight_error:
        return {
            "status": "error",
            "operation": "update_keyword_status",
            "customer_id": customer_id,
            **preflight_error,
        }

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
            "provider_request_id": result["provider_request_id"],
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
