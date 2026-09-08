# bucket: defer
"""Tool: get_recommendations - Google Ads recommendations pending for account."""

from typing import Any

from src.google_ads.queries.recommendations import TYPE_PT, recommendations_query
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {
            "type": "string",
            "pattern": "^[0-9]{10}$",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 1000,
            "default": 100,
            "description": "Máximo de recomendacoes retornadas. truncated:true se exceder.",
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


# C2: a tabela PT-BR mudou de casa (src/google_ads/queries/recommendations.py)
# porque o `apply_recommendation` passou a mostrar o MESMO rotulo no preview de
# confirmacao. Duas copias divergiriam: o gestor leria um nome ao listar e outro
# ao confirmar. O alias local existe so pra nao mexer nos call sites.
_TYPE_PT = TYPE_PT


def _row_formatter(row: Any) -> dict[str, Any]:
    rec = row.recommendation
    # proto-plus IntEnum: str(v) returns the int as string ("29"); .name gives "SITELINK_ASSET".
    # Fall back to str() for plain strings (used by unit-test mocks).
    rec_type = rec.type
    type_str = rec_type.name if hasattr(rec_type, "name") else str(rec_type)
    return {
        "resource_name": rec.resource_name,
        "type": type_str,
        "type_pt": _TYPE_PT.get(type_str),  # None when no PT-BR mapping exists
    }


@register_tool(
    name="get_recommendations",
    description=(
        "[DEFER] Recomendacoes pendentes do Google Ads pra conta: tipo (com type_pt em "
        "PT-BR quando reconhecido, null caso contrario) e resource_name pra aplicar "
        "via apply_recommendation "
        "ou dispensar via dismiss_recommendation. Para ver impacto detalhado de "
        "uma recomendacao especifica, use run_gaql filtrando por recommendation.type. "
        "limit (default 100, max 1000): as recomendacoes escalam com o nº de "
        "ad_groups, entao contas grandes truncam — `truncated:true` avisa."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def get_recommendations(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    limit = args.get("limit", 100)
    rows = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=recommendations_query(limit=limit),
        row_formatter=_row_formatter,
        operation_name="get_recommendations",
        audit_this_call=True,  # sensitive: lists actionable changes
    )
    # F98 — a query pede `limit + 1`; a linha sentinela denuncia o corte e NÃO
    # pode chegar ao gestor.
    truncated = len(rows) > limit
    rows = rows[:limit]
    return {
        "customer_id": customer_id,
        "count": len(rows),
        "truncated": truncated,
        "recommendations": rows,
    }
