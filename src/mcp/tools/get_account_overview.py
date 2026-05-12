"""Tool: get_account_overview - KPIs for date range with previous-period comparison."""

from typing import Any

from src.google_ads.queries._common import (
    get_comparison_range,
    micros_to_currency,
    parse_date_range,
    value_proxy_warning,
)
from src.google_ads.queries.overview import overview_query
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {
            "type": "string",
            "description": "ID da conta Google Ads (10 digitos, sem tracos)",
            "pattern": "^[0-9]{10}$",
        },
        "date_range": {
            "description": (
                "Periodo. Aceita preset string (LAST_7_DAYS, LAST_30_DAYS, "
                "THIS_MONTH, LAST_MONTH, YESTERDAY, TODAY, etc) ou objeto "
                "{from: 'YYYY-MM-DD', to: 'YYYY-MM-DD'}."
            ),
            "default": "LAST_30_DAYS",
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Sum the per-day rows into single totals + computed ratios."""
    if not rows:
        return {
            "impressions": 0,
            "clicks": 0,
            "cost_brl": 0.0,
            "conversions": 0.0,
            "conversions_value_brl": 0.0,
            "ctr": 0.0,
            "average_cpc_brl": 0.0,
            "cost_per_conversion_brl": 0.0,
            "roas": 0.0,
        }
    impr = sum(r["impressions"] for r in rows)
    clicks = sum(r["clicks"] for r in rows)
    cost = sum(r["cost_micros"] for r in rows)
    conv = sum(r["conversions"] for r in rows)
    conv_val = sum(r["conversions_value"] for r in rows)
    aggregate = {
        "impressions": impr,
        "clicks": clicks,
        "cost_brl": micros_to_currency(cost),
        "conversions": round(conv, 2),
        "conversions_value_brl": round(conv_val, 2),
        "ctr": round(clicks / impr, 4) if impr else 0.0,
        "average_cpc_brl": micros_to_currency(cost / clicks) if clicks else 0.0,
        "cost_per_conversion_brl": micros_to_currency(cost / conv) if conv else 0.0,
        "roas": round(conv_val / micros_to_currency(cost), 2) if cost else 0.0,
    }
    # UX-1: detect tracking placeholder (conversions_value == conversions exact 1:1)
    warning = value_proxy_warning(aggregate["conversions"], aggregate["conversions_value_brl"])
    if warning:
        aggregate["tracking_warning"] = warning
    return aggregate


def _row_formatter(row: Any) -> dict[str, Any]:
    m = row.metrics
    return {
        "impressions": int(m.impressions),
        "clicks": int(m.clicks),
        "cost_micros": int(m.cost_micros),
        "conversions": float(m.conversions),
        "conversions_value": float(m.conversions_value),
    }


@register_tool(
    name="get_account_overview",
    description=(
        "KPIs consolidados de uma conta Google Ads (impressoes, clicks, custo, "
        "conversoes, valor, CTR, CPC, CPA, ROAS) para um periodo, com comparativo "
        "do periodo imediatamente anterior de mesma duracao."
    ),
    input_schema=_SCHEMA,
)
async def get_account_overview(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    date_range = args.get("date_range", "LAST_30_DAYS")
    start, end = parse_date_range(date_range)
    prev_start, prev_end = get_comparison_range(start, end)

    rows_curr = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=overview_query(start, end),
        row_formatter=_row_formatter,
        operation_name="get_account_overview",
    )
    rows_prev = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=overview_query(prev_start, prev_end),
        row_formatter=_row_formatter,
        operation_name="get_account_overview",
    )

    return {
        "customer_id": customer_id,
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "previous_period": {"from": prev_start.isoformat(), "to": prev_end.isoformat()},
        "current": _aggregate(rows_curr),
        "previous": _aggregate(rows_prev),
    }
