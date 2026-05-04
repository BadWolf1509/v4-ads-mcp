"""Tool: validate_gaql - dry-run validate a GAQL query without consuming quota for data."""

from typing import Any

from src.google_ads.client import build_client_for_manager
from src.google_ads.errors import to_friendly
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "query": {"type": "string", "minLength": 10},
    },
    "required": ["customer_id", "query"],
    "additionalProperties": False,
}


@register_tool(
    name="validate_gaql",
    description=(
        "Valida sintaxe + nomes de campos de um GAQL sem consumir quota de "
        "dados. Retorna {valid: bool, error: str|null}. Use antes de run_gaql "
        "pra evitar gastar quota com queries quebradas."
    ),
    input_schema=_SCHEMA,
)
async def validate_gaql(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    query = args["query"]

    client = await build_client_for_manager(manager_id=ctx.manager_id)

    try:
        ga_service = client.get_service("GoogleAdsService")
        request = client.get_type("SearchGoogleAdsRequest")
        request.customer_id = customer_id
        request.query = query
        request.validate_only = True
        ga_service.search(request=request)
        return {"valid": True, "error": None}
    except Exception as e:
        try:
            friendly = to_friendly(e)
            return {"valid": False, "error": friendly.message_pt, "code": friendly.code}
        except Exception:
            return {"valid": False, "error": str(e), "code": None}
