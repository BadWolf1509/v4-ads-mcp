"""Tool: get_top_keywords_creatives - top N keywords + top N RSAs by metric."""

from typing import Any

from src.google_ads.queries._common import micros_to_currency, parse_date_range
from src.google_ads.queries.client_report import top_creatives_query, top_keywords_query
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "date_range": {"default": "LAST_30_DAYS"},
        "top_n": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
        "metric": {
            "type": "string",
            "enum": ["cost", "conversions", "clicks", "impressions"],
            "default": "cost",
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


def _kw_formatter(row: Any) -> dict[str, Any]:
    m = row.metrics
    impr = int(m.impressions)
    clicks = int(m.clicks)
    cost_micros = int(m.cost_micros)
    return {
        "criterion_id": str(row.ad_group_criterion.criterion_id),
        "keyword_text": row.ad_group_criterion.keyword.text,
        "match_type": str(row.ad_group_criterion.keyword.match_type).split(".")[-1],
        "campaign_name": row.campaign.name,
        "ad_group_name": row.ad_group.name,
        "impressions": impr,
        "clicks": clicks,
        "cost_brl": micros_to_currency(cost_micros),
        "conversions": round(float(m.conversions), 2),
        "conversions_value_brl": round(float(m.conversions_value), 2),
    }


def _ad_formatter(row: Any) -> dict[str, Any]:
    m = row.metrics
    ad = row.ad_group_ad.ad
    rsa = ad.responsive_search_ad
    headlines = [h.text for h in rsa.headlines] if rsa else []
    descriptions = [d.text for d in rsa.descriptions] if rsa else []
    impr = int(m.impressions)
    clicks = int(m.clicks)
    cost_micros = int(m.cost_micros)
    return {
        "ad_id": str(ad.id),
        "headlines": headlines,
        "descriptions": descriptions,
        "ad_strength": str(row.ad_group_ad.ad_strength).split(".")[-1],
        "campaign_name": row.campaign.name,
        "ad_group_name": row.ad_group.name,
        "impressions": impr,
        "clicks": clicks,
        "cost_brl": micros_to_currency(cost_micros),
        "conversions": round(float(m.conversions), 2),
        "conversions_value_brl": round(float(m.conversions_value), 2),
    }


_METRIC_KEY = {
    "cost": "cost_brl",
    "conversions": "conversions",
    "clicks": "clicks",
    "impressions": "impressions",
}


@register_tool(
    name="get_top_keywords_creatives",
    description=(
        "Top N palavras-chave + top N anuncios (RSAs) ranqueados por metrica "
        "configuravel (cost, conversions, clicks, impressions). Default top_n=10, "
        "metric=cost. Util pra relatorio cliente — secao de destaques."
    ),
    input_schema=_SCHEMA,
)
async def get_top_keywords_creatives(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    start, end = parse_date_range(args.get("date_range", "LAST_30_DAYS"))
    top_n = args.get("top_n", 10)
    metric = args.get("metric", "cost")
    metric_key = _METRIC_KEY[metric]

    keywords = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=top_keywords_query(start, end, top_n),
        row_formatter=_kw_formatter,
        operation_name="get_top_keywords_creatives",
    )
    creatives = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=top_creatives_query(start, end, top_n),
        row_formatter=_ad_formatter,
        operation_name="get_top_keywords_creatives",
    )

    # GAQL ORDER BY is fixed to cost_micros; if user wants a different metric,
    # re-sort client-side and truncate.
    if metric != "cost":
        keywords = sorted(keywords, key=lambda r: -r[metric_key])[:top_n]
        creatives = sorted(creatives, key=lambda r: -r[metric_key])[:top_n]

    return {
        "customer_id": customer_id,
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "metric": metric,
        "top_keywords": keywords,
        "top_creatives": creatives,
    }
