# bucket: n/a — helper module, not a registered tool
"""Núcleo compartilhado do trio meta_get_{campaign,ad_set,ad}_performance (Task 3.3).

Os 3 tools de performance Meta MCP (campaign/ad_set/ad) eram ~92% idênticos:
resolve date window → lookup ad_account (mesma msg "não encontrada" repetida) →
build_insights_call → run_meta_graph_get → parse+sort rows → envelope de sucesso.
Só variava `level` (+ nome do tool/operation_name pro audit_log).

`_run_meta_level_performance` parametriza por `level` ("campaign"|"adset"|"ad") e é
chamado pelos 3 wrappers finos em meta_get_campaign_performance.py /
meta_get_ad_set_performance.py / meta_get_ad_performance.py. Os 3 tools públicos
(nome, schema, registro, operation_name no audit_log) ficam INALTERADOS — mudança
puramente aditiva/interna.

`meta_account_not_found_error` centraliza a mensagem de conta-não-encontrada, hoje
repetida em 5 sites (os 3 deste trio + meta_get_account_overview +
meta_get_performance_breakdown) — uma fonte única.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from src.db import connection
from src.db.repositories import meta_ad_accounts
from src.mcp.tools._meta_common import meta_error_message
from src.meta_ads.account_overview import resolve_meta_date_window
from src.meta_ads.insights import Level, build_insights_call, parse_insights_row
from src.meta_ads.reports import run_meta_graph_get


def meta_account_not_found_error(ad_account_id: str) -> dict[str, Any]:
    """Envelope de erro padrão quando `ad_account_id` não está em meta_ad_accounts.

    Uma fonte pra mensagem repetida em 5 call sites (F-classe: mensagem duplicada
    diverge silenciosamente se só 1 site for atualizado no futuro).
    """
    return {
        "status": "error",
        "error_message": (
            f"Ad account {ad_account_id} não encontrada. "
            f"Use meta_refresh_accounts ou reconnect via /oauth/meta/start."
        ),
    }


async def run_meta_level_performance(
    *,
    level: Level,
    operation_name: str,
    manager_id: UUID,
    session_id: UUID,
    ad_account_id: str,
    date_range: str | None,
    start_date: str | None,
    end_date: str | None,
    limit: int,
) -> dict[str, Any]:
    """Core logic compartilhado pelo trio de performance Meta (campaign/adset/ad).

    Args:
        level: granularidade Meta Insights — "campaign" | "adset" | "ad".
        operation_name: nome do tool pro audit_log + params_summary (varia por
            call site: meta_get_campaign_performance / meta_get_ad_set_performance /
            meta_get_ad_performance) — preserva o operation_name original de cada
            tool no audit_log (não colapsa os 3 num nome genérico).
        manager_id, session_id: contexto MCP (de ctx = get_current() no wrapper).
        ad_account_id, date_range, start_date, end_date, limit: args do tool.

    Returns:
        Envelope {"status": "success", ..., "rows": [...], "total_rows": N} ou
        {"status": "error", "error_message": ...}. Shape idêntico ao que cada
        tool retornava antes da dedup (paridade bit-a-bit).
    """
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
            return meta_account_not_found_error(ad_account_id)

    edge, params = build_insights_call(
        level=level,
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
            operation_name=operation_name,
            estimated_calls=1,
            audit_this_call=True,
            params_summary={
                "ad_account_id": ad_account_id,
                "level": level,
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
        )
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "error_message": meta_error_message(e)}

    rows = [parse_insights_row(r, level) for r in resp.get("data", [])]
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
