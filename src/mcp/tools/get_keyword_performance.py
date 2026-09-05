# bucket: always
"""Tool: get_keyword_performance - per-keyword metrics + Quality Score."""

from typing import Any

from src.google_ads.account_clock import resolve_account_today
from src.google_ads.queries._common import micros_to_currency, resolve_date_window
from src.google_ads.queries.tactical import keyword_performance_query
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
        "limit": {"type": "integer", "minimum": 1, "maximum": 10000, "default": 200},
        "min_cost_brl": {
            "type": "number",
            "minimum": 0,
            "description": "Filtro server-side: só linhas com custo (BRL) >= este valor. Corta a cauda de baixo gasto (reduz payload).",
        },
        "min_clicks": {
            "type": "integer",
            "minimum": 0,
            "description": "Filtro server-side: só linhas com clicks >= este valor.",
        },
        "min_conversions": {
            "type": "number",
            "minimum": 0,
            "description": "Filtro server-side: só linhas com conversions ESTRITAMENTE acima deste valor (GAQL não aceita >= em conversions). Use 0 pra 'tem ao menos uma conversão'.",
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


def _row_formatter(row: Any) -> dict[str, Any]:
    m = row.metrics
    qi = row.ad_group_criterion.quality_info
    pe = row.ad_group_criterion.position_estimates
    impr = int(m.impressions)
    clicks = int(m.clicks)
    cost_micros = int(m.cost_micros)
    return {
        "criterion_id": str(row.ad_group_criterion.criterion_id),
        "keyword_text": row.ad_group_criterion.keyword.text,
        "match_type": row.ad_group_criterion.keyword.match_type.name,
        "status": row.ad_group_criterion.status.name,
        "negative": bool(row.ad_group_criterion.negative),  # B9 (F56)
        "quality_score": int(qi.quality_score) if qi.quality_score else None,
        "quality_creative": qi.creative_quality_score.name if qi.creative_quality_score else None,
        "quality_post_click": qi.post_click_quality_score.name
        if qi.post_click_quality_score
        else None,
        "quality_search_predicted_ctr": qi.search_predicted_ctr.name
        if qi.search_predicted_ctr
        else None,
        "first_page_cpc_brl": micros_to_currency(pe.first_page_cpc_micros)
        if pe.first_page_cpc_micros
        else None,
        "top_of_page_cpc_brl": micros_to_currency(pe.top_of_page_cpc_micros)
        if pe.top_of_page_cpc_micros
        else None,
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
    name="get_keyword_performance",
    description=(
        "[CORE] Prefira get_performance_breakdown(level=keyword) — este report sera "
        "arquivado (Fase 2B). Performance por palavra-chave com Quality Score completo (3 componentes: "
        "creative, post_click, search_predicted_ctr) + estimativas de first_page_cpc "
        "e top_of_page_cpc. Filtros: status (enabled|paused|removed|all), limit. "
        "ATENÇÃO (F56): retorna positive E negative ad_group_criterion indistintamente. "
        "Cada row tem field `negative: bool` — filtre `negative=false` no consumer pra "
        "workflows de PAUSE/análise QS, OU use `audit_zombie_keywords`/`audit_quality_score` "
        "(filtram `negative=FALSE` server-side)."
    ),
    input_schema=_SCHEMA,
    bucket="always",
)
async def get_keyword_performance(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    today = await resolve_account_today(customer_id)
    start, end = resolve_date_window(
        date_range=args.get("date_range", "LAST_30_DAYS"),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
        today=today,
    )
    status = args.get("status", "enabled")
    limit = args.get("limit", 200)
    rows = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=keyword_performance_query(
            start,
            end,
            status,
            limit,
            min_cost_brl=args.get("min_cost_brl"),
            min_clicks=args.get("min_clicks"),
            min_conversions=args.get("min_conversions"),
        ),
        row_formatter=_row_formatter,
        operation_name="get_keyword_performance",
        audit_this_call=True,
    )
    return {
        "customer_id": customer_id,
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "rows": rows,
    }
