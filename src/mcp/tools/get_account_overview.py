# bucket: defer
"""Tool: get_account_overview - KPIs for date range with previous-period comparison."""

from typing import Any

from src.google_ads.account_clock import resolve_account_today
from src.google_ads.queries._common import (
    arredondado,
    em_moeda,
    get_comparison_range,
    micros_to_currency,
    razao,
    resolve_date_window,
    value_proxy_warning,
)
from src.google_ads.queries.overview import overview_query
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
        "customer_id": {
            "type": "string",
            "description": "ID da conta Google Ads (10 digitos, sem tracos)",
            "pattern": "^[0-9]{10}$",
        },
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
            "description": (
                "Data final YYYY-MM-DD inclusive. Obrigatorio se start_date informado."
            ),
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Sum the per-day rows into single totals + computed ratios.

    Razao sem denominador vem `None` (indefinida), nao 0.0 (spec 2026-09-25,
    §4.2). Periodo sem nenhuma linha traz as contagens em 0 — verdade: nao houve
    impressao, clique nem gasto — e `sem_dados_no_periodo: True`, que distingue
    "nao ha dado" de uma linha medida com zero.
    """
    if not rows:
        return {
            "impressions": 0,
            "clicks": 0,
            "cost_brl": 0.0,
            "conversions": 0.0,
            "conversions_value_brl": 0.0,
            "ctr": None,
            "average_cpc_brl": None,
            "cost_per_conversion_brl": None,
            "roas": None,
            "sem_dados_no_periodo": True,
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
        "ctr": arredondado(razao(clicks, impr), 4),
        "average_cpc_brl": em_moeda(razao(cost, clicks)),
        "cost_per_conversion_brl": em_moeda(razao(cost, conv)),
        # O guarda antigo era `if cost` (micros) e dividia por `micros_to_currency(cost)`:
        # custo abaixo de meio centavo arredonda para 0.0 e dava ZeroDivisionError.
        "roas": arredondado(razao(conv_val, micros_to_currency(cost)), 2),
        "sem_dados_no_periodo": False,
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
        "[DEFER] KPIs consolidados de uma conta Google Ads (impressoes, clicks, custo, "
        "conversoes, valor, CTR, CPC, CPA, ROAS) para um periodo, com comparativo "
        "do periodo imediatamente anterior de mesma duracao."
        " Razao com denominador zero vem null (indefinida), nao 0."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def get_account_overview(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    today = await resolve_account_today(customer_id)
    start, end = resolve_date_window(
        date_range=args.get("date_range", "LAST_30_DAYS"),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
        today=today,
    )
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
