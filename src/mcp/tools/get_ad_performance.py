"""Tool: get_ad_performance - RSA performance + ad_strength + headlines/descriptions."""

from typing import Any

from src.google_ads.queries._common import micros_to_currency, parse_date_range
from src.google_ads.queries.tactical import ad_performance_query
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "date_range": {"default": "LAST_30_DAYS"},
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
        "status": str(row.ad_group_ad.status).split(".")[-1],
        "type": str(ad.type).split(".")[-1],
        "ad_strength": str(row.ad_group_ad.ad_strength).split(".")[-1],
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
        "Performance por anuncio (RSA) com headlines, descriptions, final_urls e "
        "ad_strength (POOR|AVERAGE|GOOD|EXCELLENT). Filtros: status, limit."
    ),
    input_schema=_SCHEMA,
)
async def get_ad_performance(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    start, end = parse_date_range(args.get("date_range", "LAST_30_DAYS"))
    status = args.get("status", "enabled")
    limit = args.get("limit", 100)
    rows = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=ad_performance_query(start, end, status, limit),
        row_formatter=_row_formatter,
        operation_name="get_ad_performance",
    )
    return {
        "customer_id": customer_id,
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "rows": rows,
    }
