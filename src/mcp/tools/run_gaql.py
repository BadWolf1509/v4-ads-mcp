"""Tool: run_gaql - escape hatch to execute arbitrary GAQL queries."""

from typing import Any

from src.google_ads.reports import execute_gaql_raw
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "query": {
            "type": "string",
            "minLength": 10,
            "description": (
                "GAQL query string. Sempre auditado. Resultado truncado em 1000 "
                "linhas. Use list_gaql_resources pra ver o catalogo de campos."
            ),
        },
    },
    "required": ["customer_id", "query"],
    "additionalProperties": False,
}

_MAX_ROWS = 1000


@register_tool(
    name="run_gaql",
    description=(
        "Escape hatch: executa qualquer GAQL contra a conta. Use apenas quando as "
        "tools curadas nao cobrem o caso. Sempre auditado. Limite: o resultado e "
        f"truncado em {_MAX_ROWS} linhas pra evitar respostas gigantes."
    ),
    input_schema=_SCHEMA,
)
async def run_gaql(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    query = args["query"]

    rows = await execute_gaql_raw(
        manager_id=ctx.manager_id,
        customer_id=customer_id,
        query=query,
    )

    truncated = len(rows) > _MAX_ROWS
    return {
        "customer_id": customer_id,
        "row_count": len(rows),
        "truncated": truncated,
        "rows": rows[:_MAX_ROWS],
    }
