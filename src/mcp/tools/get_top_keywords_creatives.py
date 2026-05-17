"""Tool: get_top_keywords_creatives - top N keywords + top N RSAs by metric."""

from typing import Any

from src.google_ads.queries._common import micros_to_currency, resolve_date_window
from src.google_ads.queries.client_report import top_creatives_query, top_keywords_query
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
        "match_type": row.ad_group_criterion.keyword.match_type.name,
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
        "ad_strength": row.ad_group_ad.ad_strength.name,
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
    start, end = resolve_date_window(
        date_range=args.get("date_range", "LAST_30_DAYS"),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
    )
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
