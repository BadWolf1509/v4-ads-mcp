# bucket: defer
"""Tool: get_geo_performance - metrics by geographic location (country level)."""

from typing import Any

from src.google_ads.queries._common import micros_to_currency, resolve_date_window
from src.google_ads.queries.performance import geo_performance_query
from src.google_ads.reports import lookup_country_names, run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_DATE_PRESETS = [
    "TODAY",
    "YESTERDAY",
    "LAST_7_DAYS",
    "LAST_14_DAYS",
    "LAST_30_DAYS",
    "LAST_90_DAYS",
    "THIS_MONTH",
    "LAST_MONTH",
    "THIS_WEEK",
    "LAST_WEEK",
]

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "date_range": {
            "type": "string",
            "enum": _DATE_PRESETS,
            "default": "LAST_30_DAYS",
            "description": "Periodo via preset. Para periodo custom, use start_date+end_date.",
        },
        "start_date": {
            "type": "string",
            "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
            "description": (
                "Data inicial YYYY-MM-DD inclusive. Quando informado junto com end_date, "
                "sobrepoe date_range preset. Obriga end_date."
            ),
        },
        "end_date": {
            "type": "string",
            "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
            "description": "Data final YYYY-MM-DD inclusive. Obrigatorio se start_date informado.",
        },
        "limit": {"type": "integer", "minimum": 1, "maximum": 10000, "default": 100},
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


def _row_formatter(row: Any) -> dict[str, Any]:
    m = row.metrics
    impr = int(m.impressions)
    clicks = int(m.clicks)
    cost_micros = int(m.cost_micros)
    return {
        "country_criterion_id": str(row.geographic_view.country_criterion_id),
        "impressions": impr,
        "clicks": clicks,
        "cost_brl": micros_to_currency(cost_micros),
        "conversions": round(float(m.conversions), 2),
        "conversions_value_brl": round(float(m.conversions_value), 2),
        "ctr": round(clicks / impr, 4) if impr else 0.0,
        "cpc_brl": micros_to_currency(cost_micros / clicks) if clicks else 0.0,
    }


@register_tool(
    name="get_geo_performance",
    description=(
        "[DEFER] Prefira get_performance_breakdown(level=account, breakdown=geo) — este "
        "report sera arquivado (Fase 2B). Performance por pais (com nome resolvido via geo_target_constant). "
        "Util pra identificar regioes underperformantes."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def get_geo_performance(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    start, end = resolve_date_window(
        date_range=args.get("date_range", "LAST_30_DAYS"),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
    )
    limit = args.get("limit", 100)
    rows = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=geo_performance_query(start, end, limit),
        row_formatter=_row_formatter,
        operation_name="get_geo_performance",
        audit_this_call=True,
    )
    # Resolve country IDs -> human-readable names via geo_target_constant.
    # Costs ~1 extra op against the API; falls back gracefully if a name is
    # missing (None) so the tool stays usable even on partial lookups.
    country_ids = {r["country_criterion_id"] for r in rows}
    country_map = await lookup_country_names(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        country_ids=country_ids,
    )
    for r in rows:
        info = country_map.get(r["country_criterion_id"])
        r["country_name"] = info["name"] if info else None
        r["country_code"] = info["country_code"] if info else None
    return {
        "customer_id": customer_id,
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "rows": rows,
    }
