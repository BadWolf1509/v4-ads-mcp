# bucket: defer
"""Tool: update_ad_group_status - pause/enable/remove ad groups."""

from typing import Any

from src.db import connection
from src.google_ads.mutations import run_mutation
from src.governance.blast_radius import RiskLevel, classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._mutate_common import applied_envelope, preview_envelope
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "ad_group_ids": {
            "type": "array",
            "items": {"type": "string", "pattern": "^[0-9]+$"},
            "minItems": 1,
        },
        "new_status": {
            "type": "string",
            "enum": ["ENABLED", "PAUSED"],
        },
    },
    "required": ["customer_id", "ad_group_ids", "new_status"],
    "additionalProperties": False,
}


@register_tool(
    name="update_ad_group_status",
    description=(
        "[DEFER] Pausa ou ativa um ou mais grupos de anuncios. Ate 5 ad_groups auto-aplica; "
        ">5 retorna preview com confirmation_token. "
        "Para REMOVER ad_groups, use Google Ads UI (tool dedicada `remove_ad_group` "
        "pode ser adicionada em sprint futura se demanda real surgir)."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def update_ad_group_status(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    ad_group_ids = args["ad_group_ids"]
    new_status = args["new_status"]
    target_count = len(ad_group_ids)

    risk = classify(
        operation="update_ad_group_status",
        params={"target_count": target_count, "new_status": new_status},
    )
    payload = {
        "ad_group_ids": ad_group_ids,
        "new_status": new_status,
        "__target_count__": target_count,
    }
    summary = (
        f"Mudar status de {target_count} grupo(s) "
        f"({', '.join(ad_group_ids[:3])}{'...' if target_count > 3 else ''}) "
        f"para {new_status}."
    )

    if risk.level == RiskLevel.AUTO:
        result = await run_mutation(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="update_ad_group_status",
            payload=payload,
            target_count=target_count,
        )
        return applied_envelope(
            "update_ad_group_status",
            customer_id,
            summary,
            applied_count=result["applied_count"],
            provider_request_id=result["provider_request_id"],
            auto_applied_reason=risk.reason,
        )

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="update_ad_group_status",
            payload=payload,
            blast_summary=summary,
        )
    return preview_envelope(
        "update_ad_group_status",
        customer_id,
        summary,
        token,
        confirmation_reason=risk.reason,
    )
