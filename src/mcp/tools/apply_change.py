"""Tool: apply_change - consume a confirmation token + execute the saved mutation."""

from typing import Any

from src.db import connection
from src.google_ads.mutations import run_mutation
from src.governance.dry_run import InvalidTokenError, consume
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "confirmation_token": {
            "type": "string",
            "pattern": "^[A-Z0-9]{8}$",
            "description": "Token de 8 chars retornado por uma tool de mutacao em modo dry-run.",
        },
    },
    "required": ["confirmation_token"],
    "additionalProperties": False,
}


@register_tool(
    name="apply_change",
    description=(
        "Confirma e aplica uma mutacao previamente previewed via dry-run. Token "
        "expira em 10 minutos. Cada token e consumivel apenas 1 vez e amarrado "
        "a sessao MCP que o gerou."
    ),
    input_schema=_SCHEMA,
)
async def apply_change(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    token = args["confirmation_token"]

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        try:
            saved = await consume(conn, token=token, session_id=ctx.session_id)
        except InvalidTokenError as e:
            return {
                "status": "error",
                "error": str(e),
            }

    target_count = int(saved.payload.get("__target_count__", 1))
    result = await run_mutation(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=saved.customer_id,
        operation_type=saved.operation_type,
        payload=saved.payload,
        target_count=target_count,
    )
    return {
        "status": "applied",
        "operation": saved.operation_type,
        "customer_id": saved.customer_id,
        "blast_summary": saved.blast_summary,
        "google_request_id": result["google_request_id"],
        "applied_count": result["applied_count"],
    }
