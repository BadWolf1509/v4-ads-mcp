# bucket: defer
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


def _augment_error_hint(query: str, friendly_message: str) -> str:
    """Append contextual hints to common GAQL errors.

    Patterns catalogados via dogfood MO-JP 2026-05-19 (B2, B3):
    - B2: FROM change_event + erro de janela 30 dias.
    - B3: segments.conversion_action* + metrics.cost_micros incompativel.

    Mensagem original sempre preservada; hint apendado como `... | Hint: ...`.
    """
    if not query or not friendly_message:
        return friendly_message

    q = query.lower()
    m = friendly_message.lower()

    # B2: change_event resource tem janela maxima 30 dias inclusive.
    # LAST_30_DAYS abrange 31 dias (hoje + 30 anteriores) e e rejeitado.
    if "from change_event" in q and ("too old" in m or "older than 30 days" in m or "30 days" in m):
        return (
            friendly_message + " | Hint: change_event tem janela maxima de 30 dias inclusive — "
            "LAST_30_DAYS conta 31 dias e e rejeitado. Use LAST_14_DAYS ou "
            "date range explicito (start_date + end_date <= 30 dias)."
        )

    # B3: segments.conversion_action* + metrics.cost_micros conflito.
    # Google rejeita "unsupported metric" quando ambos no SELECT.
    if (
        "segments.conversion_action" in q
        and "metrics.cost_micros" in q
        and ("unsupported metric" in m or "unsupported metrics" in m)
    ):
        return (
            friendly_message
            + " | Hint: segments.conversion_action* nao combina com metrics.cost_micros "
            "no mesmo SELECT. Use 2 queries separadas: (1) conv por action com "
            "segments.conversion_action sem cost; (2) cost agregado por campaign "
            "sem segments."
        )

    return friendly_message


@register_tool(
    name="validate_gaql",
    description=(
        "[DEFER] Valida sintaxe + nomes de campos de um GAQL sem consumir quota de "
        "dados. Retorna {valid: bool, error: str|null}. Use antes de run_gaql "
        "pra evitar gastar quota com queries quebradas."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
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
            hinted = _augment_error_hint(query, friendly.message_pt)
            return {"valid": False, "error": hinted, "code": friendly.code}
        except Exception:
            hinted = _augment_error_hint(query, str(e))
            return {"valid": False, "error": hinted, "code": None}
