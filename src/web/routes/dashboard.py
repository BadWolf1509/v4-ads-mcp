"""Dashboard do painel (`/`): hero editorial, números operacionais e extras do admin."""

from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from src.db import connection
from src.db.repositories import google_oauth_connections, manager_account_access, mcp_sessions
from src.web import numeros
from src.web.deps import CurrentUser, current_manager
from src.web.routes._shared import templates

router = APIRouter(tags=["web"])


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    """Dashboard: editorial hero + operational stats + admin extras."""

    # F76/F77/F91 — leitura idempotente, sobrevive a reconexão (Task 6, PR 5).
    async def _load(
        conn: asyncpg.Connection,
    ) -> tuple[
        list[Any],
        list[mcp_sessions.McpSession],
        google_oauth_connections.OAuthConnection | None,
        list[asyncpg.Record],
        int,
        list[int],
        dict[str, Any] | None,
    ]:
        accounts = await manager_account_access.list_accounts_for_manager(conn, user.id)
        active_sessions = await mcp_sessions.list_for_manager(conn, user.id, include_revoked=False)
        oauth_conn = await google_oauth_connections.get_active_for_manager(conn, user.id)

        # Recent calls (last 5 by this manager)
        recent = await conn.fetch(
            """SELECT occurred_at, operation, customer_id, status,
                      (SELECT descriptive_name FROM google_ads_accounts a
                       WHERE a.customer_id = al.customer_id LIMIT 1) AS account_name
               FROM audit_log al
               WHERE manager_id = $1
               ORDER BY occurred_at DESC, id DESC LIMIT 5""",
            user.id,
        )

        # Calls today (count + sparkline of last 7 days). O dia é o do painel
        # (America/Sao_Paulo), não o do banco (UTC) — ver src/web/numeros.py.
        sparkline_values = await numeros.contagem_por_dia(
            conn, numeros.dias_do_painel(7), manager_id=user.id
        )
        calls_today = sparkline_values[-1]

        admin_ops = None
        if user.is_admin:
            from src.db.repositories import managers as managers_repo

            admin_ops = {
                "pending_invites": await managers_repo.count_invited(conn),
                **await numeros.admin_ops(conn),
                "quota_max": 15000,
            }

        return (
            accounts,
            active_sessions,
            oauth_conn,
            recent,
            calls_today,
            sparkline_values,
            admin_ops,
        )

    (
        accounts,
        active_sessions,
        oauth_conn,
        recent,
        calls_today,
        sparkline_values,
        admin_ops,
    ) = await connection.run_with_reconnect(_load)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "current_user": user,
            "accounts_count": len(accounts),
            "sessions_count": len(active_sessions),
            "oauth_email": oauth_conn.google_email if oauth_conn else None,
            "oauth_connected_at": oauth_conn.connected_at if oauth_conn else None,
            "calls_today": calls_today,
            "calls_sparkline": sparkline_values,
            "recent_calls": [dict(r) for r in recent],
            "admin_ops": admin_ops,
        },
    )
