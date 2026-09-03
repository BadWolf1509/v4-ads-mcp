# bucket: defer
"""Tool: get_funnel_metrics - full funnel impressions -> clicks -> conv -> revenue."""

from typing import Any

from src.google_ads.account_clock import resolve_account_today
from src.google_ads.queries._common import (
    micros_to_currency,
    resolve_date_window,
    value_proxy_warning,
)
from src.google_ads.queries.client_report import funnel_query
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
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


def _row_formatter(row: Any) -> dict[str, Any]:
    m = row.metrics
    return {
        "impressions": int(m.impressions),
        "clicks": int(m.clicks),
        "cost_micros": int(m.cost_micros),
        "conversions": float(m.conversions),
        "conversions_value": float(m.conversions_value),
    }


def _build_funnel(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate rows + compute funnel rates."""
    impr = sum(r["impressions"] for r in rows)
    clicks = sum(r["clicks"] for r in rows)
    cost = sum(r["cost_micros"] for r in rows)
    conv = sum(r["conversions"] for r in rows)
    conv_val = sum(r["conversions_value"] for r in rows)

    cost_brl = micros_to_currency(cost)

    totals: dict[str, Any] = {
        "cost_brl": cost_brl,
        "conversions_value_brl": round(conv_val, 2),
        "roas": round(conv_val / cost_brl, 2) if cost_brl else 0.0,
        "average_order_value_brl": round(conv_val / conv, 2) if conv else 0.0,
        "cost_per_conversion_brl": round(cost_brl / conv, 2) if conv else 0.0,
    }
    # UX-1: detect tracking placeholder
    warning = value_proxy_warning(round(conv, 2), totals["conversions_value_brl"])
    if warning:
        totals["tracking_warning"] = warning

    return {
        "stages": [
            {"stage": "impressions", "value": impr},
            {
                "stage": "clicks",
                "value": clicks,
                "rate_from_prev_pct": round(clicks / impr * 100, 2) if impr else 0.0,
            },
            {
                "stage": "conversions",
                "value": round(conv, 2),
                "rate_from_prev_pct": round(conv / clicks * 100, 2) if clicks else 0.0,
            },
        ],
        "totals": totals,
    }


@register_tool(
    name="get_funnel_metrics",
    description=(
        "[DEFER] Funil completo da conta: impressoes -> clicks -> conversoes -> valor "
        "(receita), com taxas de conversao entre etapas e KPIs derivados (ROAS, "
        "AOV, CPA). Util pra relatorio cliente."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def get_funnel_metrics(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    today = await resolve_account_today(customer_id)
    start, end = resolve_date_window(
        date_range=args.get("date_range", "LAST_30_DAYS"),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
        today=today,
    )
    rows = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=funnel_query(start, end),
        row_formatter=_row_formatter,
        operation_name="get_funnel_metrics",
    )
    return {
        "customer_id": customer_id,
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "funnel": _build_funnel(rows),
    }
