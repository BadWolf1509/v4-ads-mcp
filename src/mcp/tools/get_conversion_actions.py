# bucket: always
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
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 1000,
            "default": 100,
            "description": "Máximo de acoes retornadas. truncated:true se exceder.",
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


def _row_formatter(row: Any) -> dict[str, Any]:
    ca = row.conversion_action
    return {
        "id": str(ca.id),
        "name": ca.name,
        "status": ca.status.name,
        "category": ca.category.name,
        "type": ca.type.name,
        "counting_type": ca.counting_type.name,
        "attribution_model": ca.attribution_model_settings.attribution_model.name,
        "default_value_brl": (
            micros_to_currency(ca.value_settings.default_value * 1_000_000)
            if ca.value_settings.default_value
            else 0.0
        ),
        "always_use_default_value": bool(ca.value_settings.always_use_default_value),
        "primary_for_goal": bool(ca.primary_for_goal),
        "include_in_conversions_metric": bool(ca.include_in_conversions_metric),
    }


@register_tool(
    name="get_conversion_actions",
    description=(
        "[CORE] Acoes de conversao configuradas na conta com status, categoria, tipo, "
        "atribuicao, valor default, primary_for_goal (Smart Bidding optimization) "
        "e include_in_conversions_metric (dashboard 'Conversions' metric). "
        "Util pra auditoria de tracking + decisao de promocao Secondary->Primary. "
        "limit (default 100, max 1000); `truncated:true` avisa quando cortou."
    ),
    input_schema=_SCHEMA,
    bucket="always",
)
async def get_conversion_actions(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    limit = args.get("limit", 100)
    rows = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=conversion_actions_query(limit=limit),
        row_formatter=_row_formatter,
        operation_name="get_conversion_actions",
        audit_this_call=True,  # sensitive: lists conversion config
    )
    # F98 — a sentinela (`limit + 1`) denuncia o corte e não chega ao gestor.
    truncated = len(rows) > limit
    rows = rows[:limit]
    return {
        "customer_id": customer_id,
        "count": len(rows),
        "truncated": truncated,
        "actions": rows,
    }
