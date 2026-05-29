# bucket: defer
"""Tool: run_gaql - escape hatch to execute arbitrary GAQL queries.

V0 (Sprint 3b.29): adiciona aggregate_by opcional pra client-side
GROUP BY + COUNT (resolve B5 token overflow em queries densas).
"""

from typing import Any

from src.google_ads.aggregation import aggregate_rows
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
        "aggregate_by": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 5,
            "description": (
                "Opcional. Lista de field paths (dotted) pra agrupar rows e contar. "
                "Ex: ['field_type','asset.type']. Retorna groups[] ordenado por count "
                "DESC ao inves de rows[]. Limite hard: 10k raw rows antes de agregar."
            ),
        },
    },
    "required": ["customer_id", "query"],
    "additionalProperties": False,
}

_MAX_ROWS = 1000
_MAX_RAW_ROWS_FOR_AGGREGATE = 10_000


@register_tool(
    name="run_gaql",
    description=(
        "[DEFER] Escape hatch: executa qualquer GAQL contra a conta. Use apenas quando as "
        "tools curadas nao cobrem o caso. Sempre auditado. Limite: resultado "
        f"truncado em {_MAX_ROWS} linhas pra evitar respostas gigantes. Suporta "
        "aggregate_by (client-side GROUP BY+COUNT) pra queries com cardinalidade "
        "alta — retorna groups[] ordenado por count DESC."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def run_gaql(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    query = args["query"]
    aggregate_by = args.get("aggregate_by")

    rows = await execute_gaql_raw(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=query,
    )

    if aggregate_by:
        if len(rows) > _MAX_RAW_ROWS_FOR_AGGREGATE:
            raise ValueError(
                f"Query retornou {len(rows)} rows (>{_MAX_RAW_ROWS_FOR_AGGREGATE}). "
                "Refine WHERE clause antes de agregar (limite hard pra evitar OOM)."
            )
        groups = aggregate_rows(rows, aggregate_by)
        truncated = len(groups) > _MAX_ROWS
        return {
            "customer_id": customer_id,
            "total_rows_scanned": len(rows),
            "group_count": len(groups),
            "truncated": truncated,
            "groups": groups[:_MAX_ROWS],
        }

    truncated = len(rows) > _MAX_ROWS
    return {
        "customer_id": customer_id,
        "row_count": len(rows),
        "truncated": truncated,
        "rows": rows[:_MAX_ROWS],
    }
