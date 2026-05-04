"""Tool: update_campaign_budget - update a campaign's daily budget. Always confirms."""

from typing import Any

from src.db import connection
from src.google_ads.queries._common import micros_to_currency
from src.google_ads.reports import run_report
from src.governance.blast_radius import classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "campaign_id": {"type": "string", "pattern": "^[0-9]+$"},
        "new_daily_budget_brl": {
            "type": "number",
            "exclusiveMinimum": 0,
            "description": "Novo orcamento diario em BRL (ex: 150.50).",
        },
    },
    "required": ["customer_id", "campaign_id", "new_daily_budget_brl"],
    "additionalProperties": False,
}


def _row_formatter(row: Any) -> dict[str, Any]:
    return {
        "campaign_budget_resource_name": row.campaign_budget.resource_name,
        "current_amount_micros": int(row.campaign_budget.amount_micros),
        "campaign_name": row.campaign.name,
    }


@register_tool(
    name="update_campaign_budget",
    description=(
        "Atualiza o orcamento diario de uma campanha. Sempre exige confirmacao "
        "via apply_change (mudancas de orcamento sao sensiveis - spec §7.1). "
        "Retorna preview com valor atual + novo + delta percentual."
    ),
    input_schema=_SCHEMA,
)
async def update_campaign_budget(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    campaign_id = args["campaign_id"]
    new_amount_brl = float(args["new_daily_budget_brl"])
    new_amount_micros = int(new_amount_brl * 1_000_000)

    # Resolve current budget + resource name via GAQL
    query = f"""
        SELECT
          campaign.id,
          campaign.name,
          campaign_budget.resource_name,
          campaign_budget.amount_micros
        FROM campaign
        WHERE campaign.id = {campaign_id}
        LIMIT 1
    """.strip()

    rows = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_row_formatter,
        operation_name="update_campaign_budget_lookup",
    )
    if not rows:
        return {
            "status": "error",
            "error": f"Campanha {campaign_id} nao encontrada na conta {customer_id}.",
        }

    info = rows[0]
    current_micros = info["current_amount_micros"]
    current_brl = micros_to_currency(current_micros)
    delta_pct = (
        ((new_amount_micros - current_micros) / current_micros * 100) if current_micros else 0.0
    )

    risk = classify(
        operation="update_campaign_budget",
        params={"target_count": 1, "delta_pct": delta_pct},
    )

    payload = {
        "campaign_budget_resource_name": info["campaign_budget_resource_name"],
        "new_amount_micros": new_amount_micros,
        "__target_count__": 1,
    }
    summary = (
        f"Orcamento de '{info['campaign_name']}' (id {campaign_id}): "
        f"R$ {current_brl} -> R$ {new_amount_brl:.2f} "
        f"(delta {delta_pct:+.1f}%)."
    )

    # Budget changes are always classify=CONFIRM per blast_radius rules
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="update_campaign_budget",
            payload=payload,
            blast_summary=summary,
        )
    return {
        "status": "dry_run",
        "operation": "update_campaign_budget",
        "customer_id": customer_id,
        "blast_summary": summary,
        "current_amount_brl": current_brl,
        "new_amount_brl": new_amount_brl,
        "delta_pct": round(delta_pct, 2),
        "confirmation_token": token,
        "expires_in_minutes": 10,
        "to_apply": "Chame apply_change(confirmation_token=<token>) para aplicar.",
        "confirmation_reason": risk.reason,
    }
