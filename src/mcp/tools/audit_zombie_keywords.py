# bucket: defer
"""Tool: audit_zombie_keywords — detectar keywords waste (impressions=0 + clicks=0).

Sprint 3b.36 — ICE 315 (#11 backlog dogfood 2026-05-19 cleanup massivo MO-JP).
Cleanup recurring tool: gestor identifica keywords ENABLED com zero activity
em window LAST_30_DAYS, pausa/remove pra reduzir waste.
"""

from typing import Any

from src.google_ads.account_clock import resolve_account_today
from src.google_ads.flag_zombie_keywords import flag_zombie_keywords
from src.google_ads.queries._common import resolve_date_window
from src.google_ads.queries.audit_zombie_keywords import (
    build_audit_zombie_keywords_query,
    dict_to_keyword_row,
    parse_keyword_view_row,
)
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "ad_group_ids": {
            "type": "array",
            "items": {"type": "string", "pattern": "^[0-9]+$"},
            "minItems": 1,
            "maxItems": 50,
            "description": "Opcional. Filtra audit a estes ad_group_ids. Default: conta inteira.",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 1000,
            "default": 200,
            "description": "Máximo zombies retornados. truncated:true se exceder.",
        },
        "date_range": {
            "type": "string",
            "enum": ["LAST_7_DAYS", "LAST_14_DAYS", "LAST_30_DAYS", "LAST_90_DAYS"],
            "default": "LAST_30_DAYS",
            "description": "Preset. Override por start_date+end_date se ambos passados.",
        },
        "start_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
            "description": (
                "Data inicial YYYY-MM-DD inclusive. Quando informado junto com end_date, "
                "sobrepoe date_range preset. Obriga end_date."
            ),
        },
        "end_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
            "description": "Data final YYYY-MM-DD inclusive. Obrigatorio se start_date informado.",
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


@register_tool(
    name="audit_zombie_keywords",
    description=(
        "[DEFER] Detecta keywords zumbis: ENABLED com zero activity (impressions=0 AND "
        "clicks=0) em window LAST_30_DAYS (default). Pre-cleanup decision tool — "
        "use pra identificar waste antes de pausar/remover em massa. Output flat "
        "list ordenada por ad_group_name ASC + keyword_text ASC pra agrupar "
        "visualmente. Filtros: ad_group_ids[] opcional, limit (default 200, max "
        "1000), date_range preset OR start_date+end_date custom. Server-side "
        "hardcoded: status=ENABLED + negative=FALSE. Sempre auditado. ATENÇÃO "
        "(F52): zumbis incluem keywords em ad_groups REMOVED (órfãs cosméticas — "
        "não competem em leilão, não impactam QS/Smart Bidding). Filtre pelo "
        "campo `ad_group_status='ENABLED'` no consumer pra cleanup de impacto "
        "técnico real, OU mantenha tudo pra inventário cosmético."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def audit_zombie_keywords(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    ad_group_ids = args.get("ad_group_ids")
    limit = args.get("limit", 200)

    today = await resolve_account_today(customer_id)
    start_date_obj, end_date_obj = resolve_date_window(
        date_range=args.get("date_range", "LAST_30_DAYS"),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
        today=today,
    )

    start_date = start_date_obj.isoformat()
    end_date = end_date_obj.isoformat()

    query = build_audit_zombie_keywords_query(
        start_date=start_date,
        end_date=end_date,
        ad_group_ids=ad_group_ids,
    )

    raw_rows = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=parse_keyword_view_row,
        operation_name="audit_zombie_keywords",
        audit_this_call=True,
        params_summary={
            "ad_group_ids": ad_group_ids,
            "limit": limit,
            "date_window": f"{start_date} to {end_date}",
        },
    )

    keyword_rows = [dict_to_keyword_row(d) for d in raw_rows]
    zombies, total = flag_zombie_keywords(keyword_rows, limit=limit)

    days = (end_date_obj - start_date_obj).days + 1

    return {
        "customer_id": customer_id,
        "date_range_resolved": {
            "start": start_date,
            "end": end_date,
            "days": days,
        },
        "filters_applied": {
            "ad_group_ids": ad_group_ids,
            "limit": limit,
        },
        "total_zombies": total,
        "truncated": total > limit,
        "returned_count": len(zombies),
        "zombies": [
            {
                "ad_group_id": z.ad_group_id,
                "ad_group_name": z.ad_group_name,
                "ad_group_status": z.ad_group_status,  # F52
                "campaign_name": z.campaign_name,
                "keyword_id": z.keyword_id,
                "keyword_text": z.keyword_text,
                "match_type": z.match_type,
                "impressions": z.impressions,
                "clicks": z.clicks,
                "cost_brl": z.cost_brl,
                "conversions": z.conversions,
                "status": z.status,
            }
            for z in zombies
        ],
    }
