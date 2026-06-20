# bucket: defer
"""Tool: get_ad_performance - RSA performance + ad_strength + headlines/descriptions."""

from typing import Any

from src.google_ads.queries._common import micros_to_currency, resolve_date_window
from src.google_ads.queries.tactical import ad_performance_query
from src.google_ads.reports import run_report
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
        "status": {
            "type": "string",
            "enum": ["enabled", "paused", "removed", "all"],
            "default": "enabled",
        },
        "limit": {"type": "integer", "minimum": 1, "maximum": 10000, "default": 100},
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


def _row_formatter(row: Any) -> dict[str, Any]:
    m = row.metrics
    ad = row.ad_group_ad.ad
    impr = int(m.impressions)
    clicks = int(m.clicks)
    cost_micros = int(m.cost_micros)
    rsa = ad.responsive_search_ad
    headlines = [h.text for h in rsa.headlines] if rsa else []
    descriptions = [d.text for d in rsa.descriptions] if rsa else []
    final_urls = list(ad.final_urls) if ad.final_urls else []
    return {
        "ad_id": str(ad.id),
        "status": row.ad_group_ad.status.name,
        "type": ad.type.name,
        "ad_strength": row.ad_group_ad.ad_strength.name,
        "headlines": headlines,
        "descriptions": descriptions,
        "final_urls": final_urls,
        "ad_group_id": str(row.ad_group.id),
        "ad_group_name": row.ad_group.name,
        "campaign_id": str(row.campaign.id),
        "campaign_name": row.campaign.name,
        "impressions": impr,
        "clicks": clicks,
        "cost_brl": micros_to_currency(cost_micros),
        "conversions": round(float(m.conversions), 2),
        "conversions_value_brl": round(float(m.conversions_value), 2),
        "ctr": round(clicks / impr, 4) if impr else 0.0,
        "cpc_brl": micros_to_currency(cost_micros / clicks) if clicks else 0.0,
    }


@register_tool(
    name="get_ad_performance",
    description=(
        "[DEFER] Performance por anuncio (RSA) com headlines, descriptions, final_urls e "
        "ad_strength (POOR|AVERAGE|GOOD|EXCELLENT). Filtros: status, limit."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def get_ad_performance(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    start, end = resolve_date_window(
        date_range=args.get("date_range", "LAST_30_DAYS"),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
    )
    status = args.get("status", "enabled")
    limit = args.get("limit", 100)
    rows = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=ad_performance_query(start, end, status, limit),
        row_formatter=_row_formatter,
        operation_name="get_ad_performance",
        audit_this_call=True,
    )
    return {
        "customer_id": customer_id,
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "rows": rows,
    }
