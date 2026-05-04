"""Tool: get_conversion_actions - conversion actions configured + status."""

from typing import Any

from src.google_ads.queries._common import micros_to_currency
from src.google_ads.queries.tactical import conversion_actions_query
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


def _row_formatter(row: Any) -> dict[str, Any]:
    ca = row.conversion_action
    return {
        "id": str(ca.id),
        "name": ca.name,
        "status": str(ca.status).split(".")[-1],
        "category": str(ca.category).split(".")[-1],
        "type": str(ca.type).split(".")[-1],
        "counting_type": str(ca.counting_type).split(".")[-1],
        "attribution_model": str(ca.attribution_model_settings.attribution_model).split(".")[-1],
        "default_value_brl": (
            micros_to_currency(ca.value_settings.default_value * 1_000_000)
            if ca.value_settings.default_value
            else 0.0
        ),
        "always_use_default_value": bool(ca.value_settings.always_use_default_value),
    }


@register_tool(
    name="get_conversion_actions",
    description=(
        "Acoes de conversao configuradas na conta com status, categoria, tipo, "
        "atribuicao e valor default. Util pra auditoria de tracking."
    ),
    input_schema=_SCHEMA,
)
async def get_conversion_actions(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    rows = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=conversion_actions_query(),
        row_formatter=_row_formatter,
        operation_name="get_conversion_actions",
        audit_this_call=True,  # sensitive: lists conversion config
    )
    return {
        "customer_id": customer_id,
        "count": len(rows),
        "actions": rows,
    }
