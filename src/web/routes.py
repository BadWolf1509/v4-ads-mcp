"""Web panel routes."""

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
    """Dashboard: quick stats + nav."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        accounts = await manager_account_access.list_accounts_for_manager(conn, user.id)
        sessions_active = await mcp_sessions.list_for_manager(conn, user.id, include_revoked=False)
        oauth_conn = await google_oauth_connections.get_active_for_manager(conn, user.id)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "current_user": user,
            "accounts_count": len(accounts),
            "sessions_count": len(sessions_active),
            "oauth_email": oauth_conn.google_email if oauth_conn else None,
            "oauth_connected_at": oauth_conn.connected_at if oauth_conn else None,
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
        {"current_user": user, "managers": [dict(r) for r in rows], "pending_invites_count": pending},
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
