"""meta_get_account_overview — 1ª tool Meta com Graph API real call (Sprint M.2b).

Single ad_account, fields essenciais, comparativo período anterior,
warnings PT-BR pra account_status problemático + token expiry <7d.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog

from src.db import connection
from src.db.repositories import meta_ad_accounts, meta_oauth_connections
from src.mcp.context import get_current
from src.mcp.tools._meta_common import META_ACCOUNT_STATUS_LABELS
from src.mcp.tools._registry import register_tool
from src.meta_ads.account_overview import (
    build_warnings,
    compute_deltas,
    parse_insights_response,
    resolve_meta_date_window,
    shift_to_previous_period,
)
from src.meta_ads.reports import run_meta_graph_get

log = structlog.get_logger(__name__)

_DESCRIPTION = (
    "Overview de uma conta Meta Ads: métricas essenciais (spend, impressões, clicks, "
    "CTR, CPC, reach, frequency, conversões, conversion_value, purchase_roas) "
    "para o período selecionado com comparativo do período anterior de mesma duração. "
    "Inclui warnings PT-BR pra account_status problemático e token OAuth expirando. "
    "Requer conexão Meta ativa (gestor deve ter conectado via /oauth/meta/start). "
    "Use meta_list_my_ad_accounts pra listar IDs disponíveis."
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
                "LAST_7_DAYS",
                "LAST_14_DAYS",
                "LAST_30_DAYS",
                "LAST_90_DAYS",
                "TODAY",
                "YESTERDAY",
            ],
            "description": (
                "Janela temporal preset. Default LAST_7_DAYS se start_date+end_date não fornecidos."
            ),
        },
        "start_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
            "description": (
                "Custom range start (YYYY-MM-DD). Sobrescreve preset. Requires end_date."
            ),
        },
        "end_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
            "description": (
                "Custom range end (YYYY-MM-DD). Sobrescreve preset. Requires start_date."
            ),
        },
    },
    "required": ["ad_account_id"],
    "additionalProperties": False,
}


async def meta_get_account_overview(
    manager_id: UUID,
    session_id: UUID,
    *,
    ad_account_id: str,
    date_range: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Account-level overview Meta com comparativo período anterior.

    Core logic — directly testable by integration tests (no context dependency).
    Handler below wraps this with get_current().
    """
    pool = connection.get_pool()

    # 1. Resolve date window
    today = datetime.now(UTC).date()
    try:
        current_start, current_end = resolve_meta_date_window(
            date_range, start_date, end_date, today
        )
    except ValueError as e:
        return {"status": "error", "error_message": f"Parâmetros de data inválidos: {e}"}
    prev_start, prev_end = shift_to_previous_period(current_start, current_end)

    # 2. Get account metadata + oauth connection
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
        oc = await meta_oauth_connections.get_active_for_manager(conn, manager_id)
        if oc is None:
            return {
                "status": "error",
                "error_message": ("Nenhuma conexão Meta ativa. Conectar via /oauth/meta/start."),
            }

    account_status_label = META_ACCOUNT_STATUS_LABELS.get(
        account.account_status or 0, "DESCONHECIDO"
    )

    fields = "spend,impressions,clicks,ctr,cpc,reach,frequency,actions,action_values,purchase_roas"

    # 3. Two Graph API calls: current period + previous period
    try:
        current_resp = await run_meta_graph_get(
            manager_id=manager_id,
            session_id=session_id,
            edge=f"/{ad_account_id}/insights",
            params={
                "fields": fields,
                "time_range": (
                    f'{{"since":"{current_start.isoformat()}","until":"{current_end.isoformat()}"}}'
                ),
                "level": "account",
                "ad_account_id": ad_account_id,
            },
            operation_name="meta_get_account_overview",
            estimated_calls=1,
            audit_this_call=True,
            params_summary={
                "ad_account_id": ad_account_id,
                "date_range": str(date_range),
                "period": "current",
                "start": current_start.isoformat(),
                "end": current_end.isoformat(),
            },
        )
        previous_resp = await run_meta_graph_get(
            manager_id=manager_id,
            session_id=session_id,
            edge=f"/{ad_account_id}/insights",
            params={
                "fields": fields,
                "time_range": (
                    f'{{"since":"{prev_start.isoformat()}","until":"{prev_end.isoformat()}"}}'
                ),
                "level": "account",
                "ad_account_id": ad_account_id,
            },
            operation_name="meta_get_account_overview",
            estimated_calls=1,
            audit_this_call=False,
        )
    except Exception as e:  # noqa: BLE001
        # MetaAdsFriendlyError has .message; fallback to str for unexpected errors
        if hasattr(e, "message"):
            return {"status": "error", "error_message": e.message}
        return {"status": "error", "error_message": str(e)}

    # 4. Parse + compute
    current_metrics = parse_insights_response(current_resp)
    previous_metrics = parse_insights_response(previous_resp)
    deltas = compute_deltas(current_metrics, previous_metrics)
    warnings = build_warnings(account_status_label, oc.token_expires_at, datetime.now(UTC))

    return {
        "status": "success",
        "ad_account_id": ad_account_id,
        "account_name": account.account_name,
        "account_status_label": account_status_label,
        "currency": account.currency,
        "date_range": {
            "start": current_start.isoformat(),
            "end": current_end.isoformat(),
        },
        "current": current_metrics,
        "previous": previous_metrics,
        "deltas": deltas,
        "_warnings": warnings,
    }


@register_tool(
    name="meta_get_account_overview",
    description=_DESCRIPTION,
    input_schema=_INPUT_SCHEMA,
)
async def _handler(args: dict[str, Any]) -> dict[str, Any]:
    """MCP tool handler — pulls context from contextvars, delegates to core function."""
    ctx = get_current()
    return await meta_get_account_overview(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        ad_account_id=args["ad_account_id"],
        date_range=args.get("date_range"),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
    )
