# bucket: defer
"""meta_get_ad_performance — Performance por anúncio (ad) Meta (Sprint M.3).

Paridade com Google get_ad_performance. Bucket=defer (granular, gestor
pede após ver campaign + ad_set levels).
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from src.db import connection
from src.db.repositories import meta_ad_accounts
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool
from src.meta_ads.account_overview import resolve_meta_date_window
from src.meta_ads.insights import build_insights_call, parse_insights_row
from src.meta_ads.reports import run_meta_graph_get

_DESCRIPTION = (
    "[DEFER] Performance por anúncio (ad) Meta Ads: spend, impressões, clicks, "
    "CTR, CPC, reach, frequency, purchases, purchases_value_brl, purchase_roas, "
    "leads. Inclui ad_set_id/name + campaign_id/name parents + creative_id. "
    "Ordenado por spend desc. Filtros: limit (max 500). "
    "[V0 limitation M.3.1] effective_status filter não suportado pela Meta Insights API."
)

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ad_account_id": {
            "type": "string",
            "pattern": r"^act_\d+$",
            "description": (
                "Meta ad account ID (formato act_<numeric>). "
                "Use meta_list_my_ad_accounts pra descobrir IDs disponíveis."
            ),
        },
        "date_range": {
            "type": "string",
            "enum": [
                "TODAY",
                "YESTERDAY",
                "LAST_7_DAYS",
                "LAST_14_DAYS",
                "LAST_30_DAYS",
                "LAST_90_DAYS",
            ],
            "description": ("Preset. Default LAST_30_DAYS se start_date+end_date não fornecidos."),
        },
        "start_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
            "description": "Custom range start. Sobrescreve preset. Requires end_date.",
        },
        "end_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
            "description": "Custom range end. Sobrescreve preset. Requires start_date.",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 500,
            "default": 100,
            "description": "Max rows. Meta API cap = 500/page.",
        },
    },
    "required": ["ad_account_id"],
    "additionalProperties": False,
}


async def meta_get_ad_performance(
    manager_id: UUID,
    session_id: UUID,
    *,
    ad_account_id: str,
    date_range: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Core logic — testable by integration tests."""
    pool = connection.get_pool()
    today = datetime.now(UTC).date()

    try:
        start, end = resolve_meta_date_window(
            date_range or "LAST_30_DAYS", start_date, end_date, today
        )
    except ValueError as e:
        return {"status": "error", "error_message": f"Datas inválidas: {e}"}

    async with pool.acquire() as conn:
        account = await meta_ad_accounts.get_by_id(conn, ad_account_id)
        if account is None:
            return {
                "status": "error",
                "error_message": (
                    f"Ad account {ad_account_id} não encontrada. "
                    f"Use meta_refresh_accounts ou reconnect via /oauth/meta/start."
                ),
            }

    edge, params = build_insights_call(
        level="ad",
        ad_account_id=ad_account_id,
        start=start,
        end=end,
        limit=limit,
    )

    try:
        resp = await run_meta_graph_get(
            manager_id=manager_id,
            session_id=session_id,
            ad_account_id=ad_account_id,
            edge=edge,
            params=params,
            operation_name="meta_get_ad_performance",
            estimated_calls=1,
            audit_this_call=True,
            params_summary={
                "ad_account_id": ad_account_id,
                "level": "ad",
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
        )
    except Exception as e:  # noqa: BLE001
        if hasattr(e, "message"):
            return {"status": "error", "error_message": e.message}
        return {"status": "error", "error_message": str(e)}

    rows = [parse_insights_row(r, "ad") for r in resp.get("data", [])]
    rows.sort(key=lambda r: r["spend_brl"], reverse=True)

    return {
        "status": "success",
        "ad_account_id": ad_account_id,
        "ad_account_name": account.account_name,
        "currency": account.currency,
        "date_range": {"start": start.isoformat(), "end": end.isoformat()},
        "rows": rows,
        "total_rows": len(rows),
    }


@register_tool(
    name="meta_get_ad_performance",
    description=_DESCRIPTION,
    input_schema=_INPUT_SCHEMA,
    bucket="defer",
)
async def handler(args: dict[str, Any]) -> dict[str, Any]:
    """MCP tool handler — pulls context from contextvars, delegates to core."""
    ctx = get_current()
    return await meta_get_ad_performance(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        ad_account_id=args["ad_account_id"],
        date_range=args.get("date_range"),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
        limit=args.get("limit", 100),
    )
