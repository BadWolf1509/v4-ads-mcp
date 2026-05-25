"""Tool: update_ad_status - pause/enable/remove individual ads (ad_group_ad)."""

from typing import Any

from src.db import connection
from src.google_ads.mutations import run_mutation
from src.governance.blast_radius import RiskLevel, classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
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
        "Pausa ou ativa um ou mais anuncios. Cada anuncio e identificado por "
        "(ad_group_id, ad_id). Ate 5 anuncios auto-aplica; >5 retorna preview "
        "com confirmation_token. Para REMOVER anuncios, use Google Ads UI (tool "
        "dedicada `remove_ad` pode ser adicionada em sprint futura se demanda real surgir)."
    ),
    input_schema=_SCHEMA,
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

    if risk.level == RiskLevel.AUTO:
        result = await run_mutation(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="update_ad_status",
            payload=payload,
            target_count=target_count,
        )
        return {
            "status": "applied",
            "operation": "update_ad_status",
            "customer_id": customer_id,
            "blast_summary": summary,
            "applied_count": result["applied_count"],
            "provider_request_id": result["provider_request_id"],
            "auto_applied_reason": risk.reason,
        }

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="update_ad_status",
            payload=payload,
            blast_summary=summary,
        )
    return {
        "status": "dry_run",
        "operation": "update_ad_status",
        "customer_id": customer_id,
        "blast_summary": summary,
        "confirmation_token": token,
        "expires_in_minutes": 10,
        "to_apply": "Chame apply_change(confirmation_token=<token>) para aplicar.",
        "confirmation_reason": risk.reason,
    }
