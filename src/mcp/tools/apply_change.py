"""Tool: apply_change - consume a confirmation token + execute the saved mutation.

Sprint 3b.26 introduces branching: operation_type=="import_offline_conversions" routes
to run_conversion_upload (ConversionUploadService); else routes to run_mutation
(GoogleAdsService.mutate).
"""

from typing import Any

from src.db import connection
from src.google_ads.conversions import run_conversion_upload
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
    params_summary = saved.payload.get("__params_summary__")  # None → default in dispatchers

    # Sprint 3b.26: branch dispatch based on operation_type.
    if saved.operation_type == "import_offline_conversions":
        # ConversionUploadService path (NOT GoogleAdsService.mutate).
        result = await run_conversion_upload(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=saved.customer_id,
            operation_type=saved.operation_type,
            payload=saved.payload,
            target_count=target_count,
            params_summary=params_summary,
        )
        # If error from dispatcher, return as-is.
        if result.get("status") == "error":
            return result
        # Conversion upload response — different shape from mutation response.
        return {
            "status": "applied",
            "operation": saved.operation_type,
            "customer_id": saved.customer_id,
            "blast_summary": saved.blast_summary,
            "google_request_id": result["google_request_id"],
            "applied_count": result["applied_count"],
            "failed_count": result["failed_count"],
            "failures": result["failures"],
        }

    # Default path: chained mutation via GoogleAdsService.mutate (Sprint 3b.1-3b.25).
    partial_failure = bool(saved.payload.get("__partial_failure__", False))
    result = await run_mutation(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=saved.customer_id,
        operation_type=saved.operation_type,
        payload=saved.payload,
        target_count=target_count,
        partial_failure=partial_failure,
        params_summary=params_summary,
    )
    return {
        "status": "applied",
        "operation": saved.operation_type,
        "customer_id": saved.customer_id,
        "blast_summary": saved.blast_summary,
        "google_request_id": result["google_request_id"],
        "applied_count": result["applied_count"],
        "resource_names": result.get("resource_names", []),
    }
