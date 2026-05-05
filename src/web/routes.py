"""Web panel routes."""

from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.auth.panel_session import PANEL_SESSION_COOKIE_NAME
from src.auth.sessions import generate_session_token, hash_session_token
from src.db import connection
from src.db.repositories import (
    google_ads_accounts,
    google_oauth_connections,
    manager_account_access,
    mcp_sessions,
)
from src.db.repositories.mcp_sessions import DEFAULT_TTL_DAYS
from src.web.deps import (
    CurrentUser,
    current_manager,
    optional_current_manager,
    pending_invites_count,
)

log = structlog.get_logger(__name__)

router = APIRouter(tags=["web"])


def _require_admin(user: CurrentUser) -> None:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")


_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@router.get("/login", response_class=HTMLResponse, response_model=None)
async def login_page(
    request: Request,
    user: CurrentUser | None = Depends(optional_current_manager),  # noqa: B008
) -> HTMLResponse | RedirectResponse:
    """Render the login page. If already logged in, redirect to dashboard."""
    if user is not None:
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"current_user": None},
    )


@router.get("/logout")
async def logout() -> RedirectResponse:
    """Clear panel session cookie + redirect to login."""
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(key=PANEL_SESSION_COOKIE_NAME, path="/")
    return response


@router.get("/help", response_class=HTMLResponse)
async def help_page(
    request: Request,
    user: CurrentUser | None = Depends(optional_current_manager),  # noqa: B008
) -> HTMLResponse:
    """Onboarding consolidated. Accessible logged-in or out (login link is included)."""
    return templates.TemplateResponse(request, "help.html", {"current_user": user})


@router.get("/access-denied", response_class=HTMLResponse, response_model=None)
async def access_denied(
    request: Request,
    reason: str = "not_invited",
) -> HTMLResponse:
    """Q8 invite-only landing page. No auth required.

    Reads a transient `v4_attempted_email` cookie set by the OAuth callback
    before redirect, so the page can show which email was rejected. Cookie is
    cleared on read so it doesn't persist or leak across logins.
    """
    attempted_email = request.cookies.get("v4_attempted_email")
    response = templates.TemplateResponse(
        request,
        "access_denied.html",
        {
            "current_user": None,
            "reason": reason,
            "attempted_email": attempted_email,
        },
    )
    response.delete_cookie("v4_attempted_email", path="/")
    return response


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    """Dashboard: editorial hero + operational stats + admin extras."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
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
               ORDER BY occurred_at DESC LIMIT 5""",
            user.id,
        )

        # Calls today (count + sparkline of last 7 days)
        today = datetime.utcnow().date()
        calls_today = (
            await conn.fetchval(
                "SELECT count(*) FROM audit_log WHERE manager_id = $1 AND occurred_at::date = $2",
                user.id,
                today,
            )
            or 0
        )
        sparkline_rows = await conn.fetch(
            """SELECT (occurred_at::date) as d, count(*) AS c
               FROM audit_log
               WHERE manager_id = $1 AND occurred_at >= $2
               GROUP BY 1 ORDER BY 1""",
            user.id,
            today - timedelta(days=6),
        )
        # Build 7-day series, filling zeros for missing days
        days = [today - timedelta(days=i) for i in range(6, -1, -1)]
        counts_by_day = {r["d"]: r["c"] for r in sparkline_rows}
        sparkline_values = [counts_by_day.get(d, 0) for d in days]

        admin_ops = None
        if user.is_admin:
            from src.db.repositories import managers as managers_repo

            pending = await managers_repo.count_invited(conn)
            errors_24h = (
                await conn.fetchval(
                    "SELECT count(*) FROM audit_log WHERE status='error' AND occurred_at > now() - interval '24 hours'",
                )
                or 0
            )
            quota_used = (
                await conn.fetchval(
                    "SELECT COALESCE(SUM(operations_used), 0) FROM rate_counters WHERE date = current_date",
                )
                or 0
            )
            active_mgrs = (
                await conn.fetchval("SELECT count(*) FROM managers WHERE status = 'active'") or 0
            )
            total_mgrs = await conn.fetchval("SELECT count(*) FROM managers") or 0
            admin_ops = {
                "pending_invites": pending,
                "quota_used": quota_used,
                "quota_max": 15000,
                "errors_24h": errors_24h,
                "active_managers": active_mgrs,
                "total_managers": total_mgrs,
            }

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
            "unidade_label": "—",  # placeholder until sub-project 2 ships
            "admin_ops": admin_ops,
        },
    )


@router.get("/sessions", response_class=HTMLResponse)
async def sessions_list(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    """List manager's MCP sessions."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        sessions = await mcp_sessions.list_for_manager(conn, user.id, include_revoked=False)

    return templates.TemplateResponse(
        request,
        "sessions/list.html",
        {
            "current_user": user,
            "sessions": sessions,
        },
    )


@router.post("/sessions/new", response_class=HTMLResponse)
async def sessions_create(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    label: str = Form(""),
    ttl_days: int = Form(DEFAULT_TTL_DAYS),
) -> HTMLResponse:
    """Create a new MCP session. Token is shown ONCE on this page."""
    if not label:
        label = "Untitled"
    if ttl_days not in (30, 60, 90, 180):
        ttl_days = DEFAULT_TTL_DAYS

    token = generate_session_token()
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        sess = await mcp_sessions.create(
            conn,
            manager_id=user.id,
            token_hash=hash_session_token(token),
            label=label,
            ttl_days=ttl_days,
        )

    # Show one-time reveal page with copy-paste snippets.
    service_url = "https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app"  # TODO: from settings
    return templates.TemplateResponse(
        request,
        "sessions/created.html",
        {
            "current_user": user,
            "session": sess,
            "token": token,
            "service_url": service_url,
            "mcp_url": f"{service_url}/mcp",
        },
    )


@router.post("/sessions/{session_id}/revoke", response_class=HTMLResponse)
async def sessions_revoke(
    request: Request,
    session_id: UUID,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    """Revoke a session. Returns updated list HTML for HTMX swap, OR redirects."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        # Confirm the session belongs to this manager (defense)
        all_sessions = await mcp_sessions.list_for_manager(conn, user.id, include_revoked=True)
        target = next((s for s in all_sessions if s.id == session_id), None)
        if target is None:
            raise HTTPException(status_code=404, detail="Session not found")
        if target.revoked_at is None:
            await mcp_sessions.revoke(conn, session_id)
        # Return fresh list
        sessions = await mcp_sessions.list_for_manager(conn, user.id, include_revoked=False)

    # If HTMX request, return just the table fragment; otherwise return full page.
    is_htmx = request.headers.get("HX-Request") == "true"
    if is_htmx:
        return templates.TemplateResponse(
            request,
            "sessions/_table.html",
            {"current_user": user, "sessions": sessions},
        )
    return templates.TemplateResponse(
        request,
        "sessions/list.html",
        {"current_user": user, "sessions": sessions},
    )


@router.get("/accounts", response_class=HTMLResponse)
async def accounts_page(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    """List Google OAuth connections + accessible Google Ads accounts."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        # All connections (including revoked, sorted most-recent first)
        all_conns = await conn.fetch(
            """
            SELECT id, google_email, scopes, connected_at, revoked_at
            FROM google_oauth_connections
            WHERE manager_id = $1
            ORDER BY connected_at DESC
            """,
            user.id,
        )
        accounts = await manager_account_access.list_accounts_for_manager(conn, user.id)

    return templates.TemplateResponse(
        request,
        "accounts.html",
        {
            "current_user": user,
            "connections": [dict(r) for r in all_conns],
            "accounts": accounts,
        },
    )


@router.post("/accounts/{connection_id}/revoke", response_class=HTMLResponse, response_model=None)
async def accounts_revoke_connection(
    request: Request,
    connection_id: UUID,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse | RedirectResponse:
    """Revoke an OAuth connection (sets revoked_at). Manager can reconnect later."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        # Verify ownership
        owner = await conn.fetchval(
            "SELECT manager_id FROM google_oauth_connections WHERE id = $1",
            connection_id,
        )
        if owner != user.id:
            raise HTTPException(status_code=404, detail="Connection not found")
        await google_oauth_connections.revoke(conn, connection_id)

    return RedirectResponse(url="/accounts", status_code=303)


@router.get("/audit", response_class=HTMLResponse)
async def audit_page(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    action_type: str = "all",  # 'mutate' | 'read' | 'all'
    customer_id: str | None = None,
    days: int = 30,
    limit: int = 100,
) -> HTMLResponse:
    """Show manager's own audit_log entries (last N days, filterable)."""
    # Sanitize input
    if action_type not in ("mutate", "read", "all"):
        action_type = "all"
    if days not in (1, 7, 14, 30, 90):
        days = 30
    if limit < 1 or limit > 1000:
        limit = 100

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        # Build query with optional filters
        where = ["manager_id = $1", f"occurred_at > now() - interval '{days} days'"]
        params: list[object] = [user.id]
        if action_type != "all":
            where.append(f"action_type = ${len(params) + 1}")
            params.append(action_type)
        if customer_id:
            where.append(f"customer_id = ${len(params) + 1}")
            params.append(customer_id)

        where_sql = " AND ".join(where)
        rows = await conn.fetch(
            f"""
            SELECT
              audit_log.occurred_at,
              audit_log.action_type,
              audit_log.operation,
              audit_log.customer_id,
              audit_log.target_count,
              audit_log.status,
              audit_log.duration_ms,
              audit_log.error_message,
              audit_log.google_request_id,
              gaa.descriptive_name AS account_name
            FROM audit_log
            LEFT JOIN google_ads_accounts gaa ON gaa.customer_id = audit_log.customer_id
            WHERE {where_sql}
            ORDER BY audit_log.occurred_at DESC
            LIMIT {limit}
            """,
            *params,
        )

        # Also fetch list of accounts the manager can see (for the filter dropdown)
        accessible = await manager_account_access.list_accounts_for_manager(conn, user.id)

    return templates.TemplateResponse(
        request,
        "audit.html",
        {
            "current_user": user,
            "rows": [dict(r) for r in rows],
            "filter_action_type": action_type,
            "filter_customer_id": customer_id or "",
            "filter_days": days,
            "accessible_accounts": accessible,
        },
    )


@router.get("/admin", response_class=HTMLResponse)
async def admin_index(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    """Admin overview: operational metrics, usage sparkline, tops, onboarding."""
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        from src.db.repositories import managers as managers_repo

        pending = await managers_repo.count_invited(conn)
        active_mgrs = (
            await conn.fetchval("SELECT count(*) FROM managers WHERE status = 'active'") or 0
        )
        total_mgrs = await conn.fetchval("SELECT count(*) FROM managers") or 0
        quota_used = (
            await conn.fetchval(
                "SELECT COALESCE(SUM(operations_used), 0) FROM rate_counters WHERE date = current_date"
            )
            or 0
        )
        errors_24h = (
            await conn.fetchval(
                "SELECT count(*) FROM audit_log WHERE status='error' AND occurred_at > now() - interval '24 hours'"
            )
            or 0
        )

        # Usage 30d sparkline
        rows_30 = await conn.fetch(
            """SELECT (occurred_at::date) AS d, count(*) AS c
               FROM audit_log
               WHERE occurred_at > now() - interval '30 days'
               GROUP BY 1 ORDER BY 1"""
        )
        usage_30d = [r["c"] for r in rows_30]

        # Top operations 7d
        top_ops = await conn.fetch(
            """SELECT operation, count(*) AS count FROM audit_log
               WHERE occurred_at > now() - interval '7 days'
               GROUP BY operation ORDER BY count DESC LIMIT 5"""
        )
        # Top managers 7d
        top_mgrs = await conn.fetch(
            """SELECT m.email, count(*) AS count
               FROM audit_log al JOIN managers m ON m.id = al.manager_id
               WHERE al.occurred_at > now() - interval '7 days'
               GROUP BY m.email ORDER BY count DESC LIMIT 5"""
        )
        # Recent onboarding (last 10 managers by created_at)
        onboarding = await conn.fetch(
            """SELECT email, status, created_at, invited_at
               FROM managers ORDER BY coalesce(invited_at, created_at) DESC LIMIT 10"""
        )

    return templates.TemplateResponse(
        request,
        "admin/index.html",
        {
            "current_user": user,
            "pending_invites": pending,
            "pending_invites_count": pending,
            "active_managers": active_mgrs,
            "total_managers": total_mgrs,
            "quota_used": quota_used,
            "quota_max": 15000,
            "errors_24h": errors_24h,
            "usage_30d": usage_30d,
            "top_operations": [dict(r) for r in top_ops],
            "top_managers": [dict(r) for r in top_mgrs],
            "recent_onboarding": [dict(r) for r in onboarding],
        },
    )


@router.get("/admin/managers", response_class=HTMLResponse)
async def admin_managers(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, email, full_name, role, is_active, created_at, last_seen_at FROM managers ORDER BY email"
        )
    pending = await pending_invites_count()
    return templates.TemplateResponse(
        request,
        "admin/managers.html",
        {
            "current_user": user,
            "managers": [dict(r) for r in rows],
            "pending_invites_count": pending,
        },
    )


@router.post("/admin/managers/{manager_id}/toggle-active", response_class=HTMLResponse)
async def admin_managers_toggle_active(
    request: Request,
    manager_id: UUID,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> RedirectResponse:
    _require_admin(user)
    if manager_id == user.id:
        raise HTTPException(status_code=400, detail="Nao pode desativar voce mesmo")
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE managers SET is_active = NOT is_active WHERE id = $1",
            manager_id,
        )
    return RedirectResponse(url="/admin/managers", status_code=303)


@router.post("/admin/managers/{manager_id}/toggle-role", response_class=HTMLResponse)
async def admin_managers_toggle_role(
    request: Request,
    manager_id: UUID,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> RedirectResponse:
    _require_admin(user)
    if manager_id == user.id:
        raise HTTPException(status_code=400, detail="Nao pode mudar seu proprio role")
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE managers SET role =
              CASE WHEN role = 'admin' THEN 'gestor' ELSE 'admin' END
            WHERE id = $1
            """,
            manager_id,
        )
    return RedirectResponse(url="/admin/managers", status_code=303)


@router.get("/admin/accounts", response_class=HTMLResponse)
async def admin_accounts(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        accs = await google_ads_accounts.list_all(conn)
    pending = await pending_invites_count()
    return templates.TemplateResponse(
        request,
        "admin/accounts.html",
        {"current_user": user, "accounts": accs, "pending_invites_count": pending},
    )


@router.get("/admin/access", response_class=HTMLResponse)
async def admin_access(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        managers_rows = await conn.fetch(
            "SELECT id, email, role, is_active FROM managers WHERE is_active = true ORDER BY email"
        )
        accs = await google_ads_accounts.list_all(conn)
        access_rows = await conn.fetch("SELECT manager_id, customer_id FROM manager_account_access")
    # Build set of (manager_id, customer_id) for quick lookup
    access_set = {(str(r["manager_id"]), r["customer_id"]) for r in access_rows}
    pending = await pending_invites_count()
    return templates.TemplateResponse(
        request,
        "admin/access.html",
        {
            "current_user": user,
            "managers_list": [dict(r) for r in managers_rows],
            "accounts": accs,
            "access_set": access_set,
            "pending_invites_count": pending,
        },
    )


@router.post("/admin/access/toggle", response_class=HTMLResponse)
async def admin_access_toggle(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    manager_id: str = Form(...),
    customer_id: str = Form(...),
) -> HTMLResponse:
    _require_admin(user)
    pool = connection.get_pool()
    target_mid = UUID(manager_id)
    async with pool.acquire() as conn:
        # Toggle: if exists, delete; else grant write
        exists = await conn.fetchval(
            "SELECT 1 FROM manager_account_access WHERE manager_id = $1 AND customer_id = $2",
            target_mid,
            customer_id,
        )
        if exists:
            await manager_account_access.revoke(
                conn,
                manager_id=target_mid,
                customer_id=customer_id,
            )
            granted = False
        else:
            await manager_account_access.grant(
                conn,
                manager_id=target_mid,
                customer_id=customer_id,
                access_level="write",
                granted_by=user.id,
            )
            granted = True

    # Return a tiny HTMX-friendly fragment that swaps the cell
    state = "checked" if granted else ""
    return HTMLResponse(
        f'<input type="checkbox" {state} '
        f'hx-post="/admin/access/toggle" '
        f'hx-vals=\'{{"manager_id": "{manager_id}", "customer_id": "{customer_id}"}}\' '
        f'hx-trigger="change" '
        f'hx-swap="outerHTML">'
    )


@router.get("/admin/invites", response_class=HTMLResponse)
async def admin_invites(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        invites = await conn.fetch(
            """SELECT m.id, m.email, m.full_name, m.invited_at,
                      inviter.email AS invited_by_email
               FROM managers m
               LEFT JOIN managers inviter ON inviter.id = m.invited_by
               WHERE m.status = 'invited'
               ORDER BY m.invited_at DESC"""
        )
    pending = await pending_invites_count()
    return templates.TemplateResponse(
        request,
        "admin/invites.html",
        {
            "current_user": user,
            "invites": [dict(r) for r in invites],
            "pending_invites_count": pending,
        },
    )


@router.post("/admin/invites/new", response_class=HTMLResponse, response_model=None)
async def admin_invites_new(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    email: str = Form(...),
    full_name: str = Form(""),
) -> RedirectResponse:
    _require_admin(user)
    email = email.strip().lower()
    if not email.endswith("@v4company.com"):
        return RedirectResponse(url="/admin/invites?error=bad_domain", status_code=303)

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        # Idempotency: if email already exists in any status, don't double-invite
        existing = await conn.fetchval("SELECT 1 FROM managers WHERE email = $1", email)
        if existing:
            return RedirectResponse(url="/admin/invites?error=exists", status_code=303)

        from src.db.repositories import managers as managers_repo

        await managers_repo.create_invited(
            conn,
            email=email,
            invited_by=user.id,
            full_name=(full_name or None),
        )
    return RedirectResponse(url="/admin/invites", status_code=303)


@router.post("/admin/invites/{invite_id}/cancel", response_class=HTMLResponse, response_model=None)
async def admin_invites_cancel(
    request: Request,
    invite_id: str,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        from src.db.repositories import managers as managers_repo

        await managers_repo.delete_invite(conn, manager_id=UUID(invite_id))
    # HTMX swap: remove the row by returning empty content
    return HTMLResponse("")


@router.get("/admin/audit", response_class=HTMLResponse)
async def admin_audit(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    manager_id: str | None = None,
    customer_id: str | None = None,
    action_type: str = "all",
    days: int = 7,
    limit: int = 200,
) -> HTMLResponse:
    _require_admin(user)
    if action_type not in ("mutate", "read", "all"):
        action_type = "all"
    if days not in (1, 7, 14, 30, 90):
        days = 7
    if limit < 1 or limit > 1000:
        limit = 200

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        where = [f"al.occurred_at > now() - interval '{days} days'"]
        params: list[object] = []
        if manager_id:
            where.append(f"al.manager_id = ${len(params) + 1}")
            params.append(UUID(manager_id))
        if customer_id:
            where.append(f"al.customer_id = ${len(params) + 1}")
            params.append(customer_id)
        if action_type != "all":
            where.append(f"al.action_type = ${len(params) + 1}")
            params.append(action_type)
        where_sql = " AND ".join(where)

        rows = await conn.fetch(
            f"""
            SELECT
              al.occurred_at,
              al.action_type,
              al.operation,
              al.customer_id,
              al.target_count,
              al.status,
              al.duration_ms,
              al.error_message,
              m.email AS manager_email,
              gaa.descriptive_name AS account_name
            FROM audit_log al
            LEFT JOIN managers m ON m.id = al.manager_id
            LEFT JOIN google_ads_accounts gaa ON gaa.customer_id = al.customer_id
            WHERE {where_sql}
            ORDER BY al.occurred_at DESC
            LIMIT {limit}
            """,
            *params,
        )
        managers_rows = await conn.fetch(
            "SELECT id, email FROM managers WHERE is_active = true ORDER BY email"
        )
        accs = await google_ads_accounts.list_all(conn)

    pending = await pending_invites_count()
    return templates.TemplateResponse(
        request,
        "admin/audit.html",
        {
            "current_user": user,
            "rows": [dict(r) for r in rows],
            "managers_list": [dict(r) for r in managers_rows],
            "accounts": accs,
            "filter_manager_id": manager_id or "",
            "filter_customer_id": customer_id or "",
            "filter_action_type": action_type,
            "filter_days": days,
            "pending_invites_count": pending,
        },
    )
