"""Tool: audit_orphan_smart_actions — detectar ConversionActions sem uso real.

Sprint 3b.37 — ICE 288 (#12 backlog dogfood 2026-05-19 cleanup massivo MO-JP).
Cleanup recurring: gestor identifica ConversionActions ENABLED com zero
conversions em window LAST_30_DAYS, pausa/remove pra reduzir noise no dashboard.
"""

from typing import Any

from src.google_ads.flag_orphan_smart_actions import flag_orphan_smart_actions
from src.google_ads.queries._common import resolve_date_window
from src.google_ads.queries.audit_orphan_smart_actions import (
    build_audit_orphan_smart_actions_query,
    dict_to_conversion_action_row,
    parse_conversion_action_row,
)
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

# Sprint 3b.19A whitelist — 13 V4-focused categorias (idêntica audit_goal_attribution 3b.35)
_V4_CATEGORIES = [
    "DEFAULT",
    "PAGE_VIEW",
    "PURCHASE",
    "SIGNUP",
    "SUBMIT_LEAD_FORM",
    "BOOK_APPOINTMENT",
    "REQUEST_QUOTE",
    "GET_DIRECTIONS",
    "OUTBOUND_CLICK",
    "CONTACT",
    "ENGAGEMENT",
    "STORE_VISIT",
    "STORE_SALE",
]

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "category": {
            "type": "string",
            "enum": _V4_CATEGORIES,
            "description": (
                "Opcional. Filtra audit a uma única ConversionAction.category. "
                "Whitelist V4 13 valores (F17/F18/F19-safe — mesma de "
                "create_conversion_action 3b.19A e audit_goal_attribution 3b.35)."
            ),
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 500,
            "default": 100,
            "description": (
                "Máximo orphans retornados. truncated:true se exceder. "
                "Default 100 (lição 3b.36: limit=200 estourou MCP cap em "
                "conta com 500+ entries)."
            ),
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
    name="audit_orphan_smart_actions",
    description=(
        "Detecta ConversionActions orphan: ENABLED com zero conversions "
        "(metrics.all_conversions=0.0) em window LAST_30_DAYS (default). "
        "Pre-cleanup decision tool — use pra identificar tracking pixels "
        "obsoletos, ações de campanhas removidas, conversion actions criadas "
        "em testes que continuam ENABLED sem trackar nada útil. Output flat "
        "list ordenada por (category, origin, name) ASC pra agrupar "
        "visualmente. Filtros: category opcional (whitelist 13 V4 valores), "
        "limit (default 100, max 500), date_range preset OR start_date+"
        "end_date custom. Server-side hardcoded: status=ENABLED. Sempre auditado."
    ),
    input_schema=_SCHEMA,
)
async def audit_orphan_smart_actions(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    category = args.get("category")
    limit = args.get("limit", 100)

    start_date_obj, end_date_obj = resolve_date_window(
        date_range=args.get("date_range", "LAST_30_DAYS"),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
    )

    start_date = start_date_obj.isoformat()
    end_date = end_date_obj.isoformat()

    query = build_audit_orphan_smart_actions_query(
        start_date=start_date,
        end_date=end_date,
        category=category,
    )

    raw_rows = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=parse_conversion_action_row,
        operation_name="audit_orphan_smart_actions",
        audit_this_call=True,
        params_summary={
            "category": category,
            "limit": limit,
            "date_window": f"{start_date} to {end_date}",
        },
    )

    action_rows = [dict_to_conversion_action_row(d) for d in raw_rows]
    orphans, total = flag_orphan_smart_actions(action_rows, limit=limit)

    days = (end_date_obj - start_date_obj).days + 1

    return {
        "customer_id": customer_id,
        "date_range_resolved": {
            "start": start_date,
            "end": end_date,
            "days": days,
        },
        "filters_applied": {
            "category": category,
            "limit": limit,
        },
        "total_orphans": total,
        "truncated": total > limit,
        "returned_count": len(orphans),
        "orphans": [
            {
                "conversion_action_id": o.conversion_action_id,
                "name": o.name,
                "category": o.category,
                "origin": o.origin,
                "primary_for_goal": o.primary_for_goal,
                "status": o.status,
                "all_conversions": o.all_conversions,
            }
            for o in orphans
        ],
    }
