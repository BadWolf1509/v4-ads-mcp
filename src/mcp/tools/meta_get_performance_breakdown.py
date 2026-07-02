# bucket: defer
"""meta_get_performance_breakdown — Performance Meta quebrada por 1 dimensão (Sprint M.4).

Consolida o conceito de breakdown numa tool: level (campaign|adset|ad) × breakdown
(platform|device|geo|hourly). Reusa run_meta_graph_get (gate+audit+BUC) +
build_insights_call/parse_insights_row estendidos. 1 breakdown por chamada (Meta
restringe combos). bucket=defer (deep-dive, não a 1ª pergunta do gestor).
"""

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from src.db import connection
from src.db.repositories import meta_ad_accounts
from src.mcp.context import get_current
from src.mcp.tools._meta_common import meta_error_message
from src.mcp.tools._registry import register_tool
from src.meta_ads.account_overview import resolve_meta_date_window
from src.meta_ads.insights import (
    BREAKDOWN_META_PARAM,
    Level,
    build_insights_call,
    parse_insights_row,
)
from src.meta_ads.reports import run_meta_graph_get

_DESCRIPTION = (
    "[DEFER] Performance Meta Ads quebrada por UMA dimensão: platform "
    "(Facebook/Instagram/Audience Network), device (iOS/Android/desktop), geo (país) "
    "ou hourly (hora do dia). level = campaign|adset|ad (default campaign). Métricas: "
    "spend, impressões, clicks, CTR, CPC, reach, frequency, purchases, purchase_roas, "
    "leads. Cada row traz o valor da dimensão em `breakdown`. Ordenado por spend desc. "
    "1 breakdown por chamada. Use meta_list_my_ad_accounts pros IDs."
)

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ad_account_id": {
            "type": "string",
            "pattern": r"^act_\d+$",
            "description": "Meta ad account ID (act_<numeric>). Use meta_list_my_ad_accounts.",
        },
        "breakdown": {
            "type": "string",
            "enum": ["platform", "device", "geo", "hourly"],
            "description": (
                "Dimensão do corte: platform (publisher_platform), device, geo (país), "
                "hourly (hora no fuso do anunciante). 1 por chamada."
            ),
        },
        "level": {
            "type": "string",
            "enum": ["campaign", "adset", "ad"],
            "description": "Nível de agregação. Default campaign.",
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
            "description": "Preset. Default LAST_30_DAYS se start_date+end_date não fornecidos.",
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
    "required": ["ad_account_id", "breakdown"],
    "additionalProperties": False,
}


async def meta_get_performance_breakdown(
    manager_id: UUID,
    session_id: UUID,
    *,
    ad_account_id: str,
    breakdown: str,
    level: str = "campaign",
    date_range: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Core logic — testable by integration tests."""
    pool = connection.get_pool()
    today = datetime.now(UTC).date()

    breakdown_params = BREAKDOWN_META_PARAM.get(breakdown)
    if breakdown_params is None:
        return {
            "status": "error",
            "error_message": (
                f"breakdown '{breakdown}' inválido. Aceitos: {sorted(BREAKDOWN_META_PARAM)}."
            ),
        }

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

    level_typed = cast(Level, level)
    edge, params = build_insights_call(
        level=level_typed,
        ad_account_id=ad_account_id,
        start=start,
        end=end,
        limit=limit,
        breakdowns=breakdown_params,
    )

    try:
        resp = await run_meta_graph_get(
            manager_id=manager_id,
            session_id=session_id,
            ad_account_id=ad_account_id,
            edge=edge,
            params=params,
            operation_name="meta_get_performance_breakdown",
            estimated_calls=1,
            audit_this_call=True,
            params_summary={
                "ad_account_id": ad_account_id,
                "level": level,
                "breakdown": breakdown,
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
        )
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "error_message": meta_error_message(e)}

    rows = [
        parse_insights_row(r, level_typed, breakdown_keys=breakdown_params)
        for r in resp.get("data", [])
    ]
    rows.sort(key=lambda r: r["spend_brl"], reverse=True)

    return {
        "status": "success",
        "ad_account_id": ad_account_id,
        "ad_account_name": account.account_name,
        "currency": account.currency,
        "level": level,
        "breakdown": breakdown,
        "date_range": {"start": start.isoformat(), "end": end.isoformat()},
        "rows": rows,
        "total_rows": len(rows),
    }


@register_tool(
    name="meta_get_performance_breakdown",
    description=_DESCRIPTION,
    input_schema=_INPUT_SCHEMA,
    bucket="defer",
)
async def handler(args: dict[str, Any]) -> dict[str, Any]:
    """MCP tool handler — pulls context from contextvars, delegates to core."""
    ctx = get_current()
    return await meta_get_performance_breakdown(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        ad_account_id=args["ad_account_id"],
        breakdown=args["breakdown"],
        level=args.get("level", "campaign"),
        date_range=args.get("date_range"),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
        limit=args.get("limit", 100),
    )
