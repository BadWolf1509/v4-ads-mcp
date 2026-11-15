# bucket: defer
"""Tool: update_ad_status - pause/enable/remove individual ads (ad_group_ad)."""

from typing import Any

from src.governance.blast_radius import classify
from src.mcp.context import get_current
from src.mcp.tools._mutate_common import aplicar_ou_pedir_confirmacao
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "ads": {
            "type": "array",
            "minItems": 1,
            "maxItems": 500,
            "items": {
                "type": "object",
                "properties": {
                    "ad_group_id": {"type": "string", "pattern": "^[0-9]+$"},
                    "ad_id": {"type": "string", "pattern": "^[0-9]+$"},
                },
                "required": ["ad_group_id", "ad_id"],
                "additionalProperties": False,
            },
        },
        "new_status": {
            "type": "string",
            "enum": ["ENABLED", "PAUSED"],
        },
    },
    "required": ["customer_id", "ads", "new_status"],
    "additionalProperties": False,
}


@register_tool(
    name="update_ad_status",
    description=(
        "[DEFER] Pausa ou ativa um ou mais anuncios. Cada anuncio e identificado por "
        "(ad_group_id, ad_id). Ate 5 anuncios auto-aplica; >5 retorna preview "
        "com confirmation_token. Para REMOVER anuncios, use remove_ad (sempre com "
        "token, irreversivel)."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def update_ad_status(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    ads = args["ads"]
    new_status = args["new_status"]
    target_count = len(ads)

    risk = classify(
        operation="update_ad_status",
        params={"target_count": target_count, "new_status": new_status},
    )
    payload = {
        "ads": ads,
        "new_status": new_status,
        "__target_count__": target_count,
    }
    summary = (
        f"Mudar status de {target_count} anuncio(s) "
        f"({', '.join(a['ad_id'] for a in ads[:3])}{'...' if target_count > 3 else ''}) "
        f"para {new_status}."
    )

    return await aplicar_ou_pedir_confirmacao(
        ctx,
        operation="update_ad_status",
        customer_id=customer_id,
        payload=payload,
        target_count=target_count,
        resumo=summary,
        risk=risk,
    )
