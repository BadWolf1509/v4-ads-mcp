# bucket: defer
"""Tool: audit_goal_attribution — pre-flight check antes de mexer em primary_for_goal.

Sprint 3b.35 — W3 do dogfood 2026-05-21 MO-JP+CAB (ICE 360).
Cruza conversion_action com customer_conversion_goal pra revelar biddable flag
por (category, origin), emitindo warning PT-BR se primary→secondary impacta
Smart Bidding. Resolve falsa premissa "cosmético KPI" descoberta em lição 47.
"""

import asyncio
from typing import Any

from src.google_ads.goal_attribution import (
    audit_goal_attribution as _audit_goal_attribution_pure,
)
from src.google_ads.goal_attribution import (
    dict_to_conversion_action_row,
    dict_to_customer_conversion_goal_row,
)
from src.google_ads.queries.audit_goal_attribution import (
    build_conversion_action_query,
    build_customer_conversion_goal_query,
    parse_conversion_action_row,
    parse_customer_conversion_goal_row,
)
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

# Sprint 3b.19A whitelist — 13 V4-focused categorias (após F17/F18/F19 fixes)
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
                "Default sem filtro = retorna todas categories da conta agrupadas "
                "por (category, origin). Whitelist V4 13 valores (mesma de "
                "create_conversion_action 3b.19A — F17/F18/F19-safe)."
            ),
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


@register_tool(
    name="audit_goal_attribution",
    description=(
        "[DEFER] Pre-flight check antes de mexer em ConversionAction.primary_for_goal. "
        "Cruza conversion_action com customer_conversion_goal pra revelar "
        "biddable flag por (category, origin). Output: origin_summary dict com "
        "biddable + warning PT-BR (null se biddable=false) + primary/secondary "
        "actions split. biddable=true significa que promover Secondary→Primary "
        "AFETA Smart Bidding em todas campaigns que usam esta category+origin — "
        "NÃO é cosmético KPI (lição 47 dogfood MO-JP). Filter opcional por "
        "category (whitelist 13 V4 valores). Apenas actions com status=ENABLED. "
        "Sempre auditado."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def audit_goal_attribution(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    category_filter = args.get("category")

    # 2 queries paralelas via asyncio.gather (padrão Sprint 3b.21 + 3b.31)
    actions_query = build_conversion_action_query()
    goals_query = build_customer_conversion_goal_query()

    actions_raw, goals_raw = await asyncio.gather(
        run_report(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            query=actions_query,
            row_formatter=parse_conversion_action_row,
            operation_name="audit_goal_attribution_actions",
            audit_this_call=True,
            params_summary={"category_filter": category_filter, "phase": "actions"},
        ),
        run_report(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            query=goals_query,
            row_formatter=parse_customer_conversion_goal_row,
            operation_name="audit_goal_attribution_goals",
            audit_this_call=True,
            params_summary={"category_filter": category_filter, "phase": "goals"},
        ),
    )

    # Boundary conversion: dict → dataclass
    actions = [dict_to_conversion_action_row(d) for d in actions_raw]
    goals = [dict_to_customer_conversion_goal_row(d) for d in goals_raw]

    # Pure aggregator
    result = _audit_goal_attribution_pure(
        actions,
        goals,
        category_filter=category_filter,
        customer_id=customer_id,
    )

    # Return dict — serialize dataclasses
    return {
        "customer_id": result.customer_id,
        "category_filter": result.category_filter,
        "origin_summary": {
            key: {
                "category": s.category,
                "origin": s.origin,
                "biddable": s.biddable,
                "warning": s.warning,
                "primary_count": s.primary_count,
                "secondary_count": s.secondary_count,
                "primary_actions": [
                    {
                        "id": a.id,
                        "name": a.name,
                        "include_in_conversions_metric": a.include_in_conversions_metric,
                        "status": a.status,
                    }
                    for a in s.primary_actions
                ],
                "secondary_actions": [
                    {
                        "id": a.id,
                        "name": a.name,
                        "include_in_conversions_metric": a.include_in_conversions_metric,
                        "status": a.status,
                    }
                    for a in s.secondary_actions
                ],
            }
            for key, s in result.origin_summary.items()
        },
        "total_actions_audited": result.total_actions_audited,
        "origins_audited": list(result.origins_audited),
        "categories_audited": list(result.categories_audited),
    }
