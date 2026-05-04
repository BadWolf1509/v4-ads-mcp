"""Tool: get_funnel_metrics - full funnel impressions -> clicks -> conv -> revenue."""

from typing import Any

from src.google_ads.queries._common import micros_to_currency, parse_date_range
from src.google_ads.queries.client_report import funnel_query
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "date_range": {"default": "LAST_30_DAYS"},
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
        "totals": {
            "cost_brl": cost_brl,
            "conversions_value_brl": round(conv_val, 2),
            "roas": round(conv_val / cost_brl, 2) if cost_brl else 0.0,
            "average_order_value_brl": round(conv_val / conv, 2) if conv else 0.0,
            "cost_per_conversion_brl": round(cost_brl / conv, 2) if conv else 0.0,
        },
    }


@register_tool(
    name="get_funnel_metrics",
    description=(
        "Funil completo da conta: impressoes -> clicks -> conversoes -> valor "
        "(receita), com taxas de conversao entre etapas e KPIs derivados (ROAS, "
        "AOV, CPA). Util pra relatorio cliente."
    ),
    input_schema=_SCHEMA,
)
async def get_funnel_metrics(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    start, end = parse_date_range(args.get("date_range", "LAST_30_DAYS"))
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
