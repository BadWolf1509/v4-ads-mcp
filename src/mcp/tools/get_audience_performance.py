"""Tool: get_audience_performance - audiences/segments applied + metrics."""

from typing import Any

from src.google_ads.queries._common import micros_to_currency, parse_date_range
from src.google_ads.queries.tactical import audience_performance_query
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "date_range": {"default": "LAST_30_DAYS"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 10000, "default": 200},
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


def _row_formatter(row: Any) -> dict[str, Any]:
    m = row.metrics
    cr = row.ad_group_criterion
    impr = int(m.impressions)
    clicks = int(m.clicks)
    cost_micros = int(m.cost_micros)
    user_list = cr.user_list.user_list if cr.user_list and cr.user_list.user_list else None
    user_interest = (
        str(cr.user_interest.user_interest_category)
        if cr.user_interest and cr.user_interest.user_interest_category
        else None
    )
    return {
        "resource_name": row.ad_group_audience_view.resource_name,
        "criterion_id": str(cr.criterion_id),
        "user_list": user_list,
        "user_interest_category": user_interest,
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
    name="get_audience_performance",
    description=(
        "Performance por audiencia/segmento aplicado em ad groups: listas de "
        "remarketing (user_list) ou interesses (user_interest_category) + metricas."
    ),
    input_schema=_SCHEMA,
)
async def get_audience_performance(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    start, end = parse_date_range(args.get("date_range", "LAST_30_DAYS"))
    limit = args.get("limit", 200)
    rows = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=audience_performance_query(start, end, limit),
        row_formatter=_row_formatter,
        operation_name="get_audience_performance",
    )
    return {
        "customer_id": customer_id,
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "rows": rows,
    }
