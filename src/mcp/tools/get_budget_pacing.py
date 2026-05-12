"""Tool: get_budget_pacing - per-campaign budget vs MTD spend + projection."""

from datetime import UTC, datetime
from typing import Any

from src.google_ads.queries._common import micros_to_currency
from src.google_ads.queries.overview import budget_pacing_query
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {
            "type": "string",
            "pattern": "^[0-9]{10}$",
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


def _row_formatter(row: Any) -> dict[str, Any]:
    return {
        "campaign_id": str(row.campaign.id),
        "campaign_name": row.campaign.name,
        "daily_budget_brl": micros_to_currency(row.campaign_budget.amount_micros),
        "delivery_method": row.campaign_budget.delivery_method.name,
        "cost_micros_today": int(row.metrics.cost_micros),
    }


def _project(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate per-campaign MTD spend + project end-of-month."""
    today = datetime.now(UTC)
    # Days in current month
    if today.month == 12:
        next_month_first = today.replace(year=today.year + 1, month=1, day=1)
    else:
        next_month_first = today.replace(month=today.month + 1, day=1)
    days_in_month = (next_month_first - today.replace(day=1)).days
    days_elapsed = today.day
    days_remaining = days_in_month - days_elapsed

    by_campaign: dict[str, dict[str, Any]] = {}
    for r in rows:
        cid = r["campaign_id"]
        if cid not in by_campaign:
            by_campaign[cid] = {
                "campaign_id": cid,
                "campaign_name": r["campaign_name"],
                "daily_budget_brl": r["daily_budget_brl"],
                "delivery_method": r["delivery_method"],
                "cost_micros_total": 0,
            }
        by_campaign[cid]["cost_micros_total"] += r["cost_micros_today"]

    out: list[dict[str, Any]] = []
    for c in by_campaign.values():
        mtd = micros_to_currency(c["cost_micros_total"])
        daily_avg = mtd / days_elapsed if days_elapsed else 0
        projected = round(daily_avg * days_in_month, 2)
        budget_monthly = round(c["daily_budget_brl"] * days_in_month, 2)
        out.append(
            {
                "campaign_id": c["campaign_id"],
                "campaign_name": c["campaign_name"],
                "daily_budget_brl": c["daily_budget_brl"],
                "spent_mtd_brl": mtd,
                "spent_pct_of_monthly_budget": round(mtd / budget_monthly * 100, 1)
                if budget_monthly
                else 0,
                "days_elapsed": days_elapsed,
                "days_remaining": days_remaining,
                "projected_monthly_brl": projected,
                "projection_vs_budget_pct": round(projected / budget_monthly * 100, 1)
                if budget_monthly
                else 0,
                "delivery_method": c["delivery_method"],
            }
        )
    return sorted(out, key=lambda x: -x["spent_mtd_brl"])


@register_tool(
    name="get_budget_pacing",
    description=(
        "Por campanha ativa: orcamento diario, gasto MTD, projecao de fim de mes, "
        "% consumido do orcamento mensal. Util pra ver no inicio do dia se alguma "
        "campanha esta acelerada/lenta demais."
    ),
    input_schema=_SCHEMA,
)
async def get_budget_pacing(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    rows = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=budget_pacing_query(),
        row_formatter=_row_formatter,
        operation_name="get_budget_pacing",
    )
    return {
        "customer_id": customer_id,
        "as_of": datetime.now(UTC).date().isoformat(),
        "campaigns": _project(rows),
    }
