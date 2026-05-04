"""Tool: list_gaql_resources - return the curated GAQL resource catalog."""

from typing import Any

from src.google_ads.queries.meta import RESOURCES, SEGMENTS
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


@register_tool(
    name="list_gaql_resources",
    description=(
        "Catalogo curado de resources GAQL (15+) com seus campos comumente usados. "
        "Inclui tambem a lista de segments aplicaveis. Use junto com run_gaql ou "
        "validate_gaql pra construir queries customizadas."
    ),
    input_schema=_SCHEMA,
)
async def list_gaql_resources(_args: dict[str, Any]) -> dict[str, Any]:
    return {
        "resources": [
            {
                "name": name,
                "description": meta["description"],
                "fields": meta["fields"],
            }
            for name, meta in RESOURCES.items()
        ],
        "segments": SEGMENTS,
    }
