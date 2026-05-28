"""Web panel routes."""

import html
import json
from collections import OrderedDict
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates

from src.auth.panel_session import PANEL_SESSION_COOKIE_NAME
from src.auth.sessions import generate_session_token, hash_session_token
from src.config import get_settings
from src.db import connection
from src.db.repositories import (
    google_ads_accounts,
    google_oauth_connections,
    manager_account_access,
    manager_meta_account_access,
    mcp_sessions,
    meta_ad_accounts,
    meta_oauth_connections,
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


def _toggle_checkbox_fragment(*, post_url: str, vals: dict[str, str], checked: bool) -> str:
    state = "checked" if checked else ""
    hx_vals = html.escape(json.dumps(vals), quote=True)
    return (
        f'<input type="checkbox" {state} hx-post="{post_url}" '
        f'hx-vals=\'{hx_vals}\' hx-trigger="change" hx-swap="outerHTML">'
    )


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


@router.post("/logout")
async def logout() -> RedirectResponse:
    """Clear panel session cookie + redirect to login. POST-only to prevent logout-CSRF."""
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


@router.get("/legal/privacy", response_class=HTMLResponse)
async def legal_privacy(
    request: Request,
    user: CurrentUser | None = Depends(optional_current_manager),  # noqa: B008
) -> HTMLResponse:
    """Public Privacy Policy. Required by Meta Marketing API App Settings."""
    return templates.TemplateResponse(request, "legal/privacy.html", {"current_user": user})


@router.get("/legal/terms", response_class=HTMLResponse)
async def legal_terms(
    request: Request,
    user: CurrentUser | None = Depends(optional_current_manager),  # noqa: B008
) -> HTMLResponse:
    """Public Terms of Service. Required by Meta Marketing API App Settings."""
    return templates.TemplateResponse(request, "legal/terms.html", {"current_user": user})


@router.get(
    "/legal/data-deletion-status/{code}", response_class=HTMLResponse, name="data_deletion_status"
)
async def data_deletion_status(
    request: Request,
    code: UUID,
    user: CurrentUser | None = Depends(optional_current_manager),  # noqa: B008
) -> HTMLResponse:
    """Public data deletion confirmation status page. Meta App Review requirement."""
    return templates.TemplateResponse(
        request,
        "legal/data_deletion_status.html",
        {"current_user": user, "confirmation_code": str(code)},
    )


@router.get("/access-denied", response_class=HTMLResponse, response_model=None)
async def access_denied(
    request: Request,
    reason: str = "not_invited",
    email: str | None = None,
    detail: str | None = None,
    missing: str | None = None,
) -> HTMLResponse:
    """Q8 invite-only landing page. No auth required.

    Reads a transient `v4_attempted_email` cookie set by the OAuth callback
    before redirect, so the page can show which email was rejected. Cookie is
    cleared on read so it doesn't persist or leak across logins.

    Also accepts Meta OAuth error params:
    - email: rejected email address (passed via query param for Meta domain check)
    - detail: error detail string (meta_oauth_error branch)
    - missing: comma-separated missing scope names (meta_scopes_missing branch)
    """
    attempted_email = request.cookies.get("v4_attempted_email") or email
    missing_scopes = missing.split(",") if missing else []
    response = templates.TemplateResponse(
        request,
        "access_denied.html",
        {
            "current_user": None,
            "reason": reason,
            "attempted_email": attempted_email,
            "email": email,
            "detail": detail,
            "missing_scopes": missing_scopes,
        },
    )
    response.delete_cookie("v4_attempted_email", path="/access-denied")
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
        today = datetime.now(UTC).date()
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


@router.get("/sessions/{session_id}", response_class=HTMLResponse)
async def session_detail(
    request: Request,
    session_id: str,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    token_flash: bool = False,
) -> HTMLResponse:
    """Permanent detail page for a single MCP session. Shows flash token once on creation."""
    try:
        parsed_session_id = UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Sessão não encontrada") from None
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        session = await mcp_sessions.get_by_id(
            conn,
            session_id=parsed_session_id,
            manager_id=user.id,
        )
    if session is None:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")

    flash_token = request.cookies.get("v4_session_flash_token") if token_flash else None
    settings = get_settings()
    mcp_url = f"{settings.public_base_url}/mcp"

    response = templates.TemplateResponse(
        request,
        "sessions/detail.html",
        {
            "current_user": user,
            "session": session,
            "flash_token": flash_token,
            "mcp_url": mcp_url,
        },
    )
    if flash_token:
        response.delete_cookie(
            "v4_session_flash_token",
            path=f"/sessions/{session_id}",
        )
    return response


@router.post("/sessions/new", response_class=HTMLResponse, response_model=None)
async def sessions_create(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    label: str = Form(""),
    ttl_days: int = Form(DEFAULT_TTL_DAYS),
) -> RedirectResponse:
    """Create a new MCP session. Redirects to /sessions/{id} with flash-token cookie."""
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

    # Redirect to permanent detail page; plaintext token travels in a transient cookie.
    response = RedirectResponse(
        url=f"/sessions/{sess.id}?token_flash=true",
        status_code=303,
    )
    response.set_cookie(
        "v4_session_flash_token",
        token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=60,  # 60 seconds — won't persist on devices away from keyboard
        path=f"/sessions/{sess.id}",  # restrict scope to the detail page
    )
    return response


@router.post("/sessions/{session_id}/revoke", response_class=HTMLResponse)
async def sessions_revoke(
    request: Request,
    session_id: UUID,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> Response:
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

    # If HTMX request, decide by the originating page.
    # Detail page (/sessions/<id>) → send HX-Redirect so HTMX navigates cleanly.
    # List page (/sessions) → swap table fragment in-place (existing behaviour).
    is_htmx = request.headers.get("HX-Request") == "true"
    if is_htmx:
        current_url = request.headers.get("HX-Current-URL", "")
        current_path = urlparse(current_url).path
        if current_path.startswith("/sessions/") and current_path.rstrip("/") != "/sessions":
            # Came from the detail page — redirect without flashing the fragment.
            return Response(status_code=204, headers={"HX-Redirect": "/sessions"})
        # Came from the list page — return fresh table fragment for in-place swap.
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
async def audit(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    action_type: str = "all",
    customer_id: str | None = None,
    status: str = "all",
    days: int = 7,
    page: int = 1,
) -> HTMLResponse:
    page_size = 50
    offset = (page - 1) * page_size

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        accounts = await manager_account_access.list_accounts_for_manager(conn, user.id)

        # Build dynamic WHERE
        where = ["al.manager_id = $1", "al.occurred_at > now() - ($2 || ' days')::interval"]
        params: list[Any] = [user.id, str(days)]
        idx = 3
        if action_type != "all":
            where.append(f"al.action_type = ${idx}")
            params.append(action_type)
            idx += 1
        if customer_id:
            where.append(f"al.customer_id = ${idx}")
            params.append(customer_id)
            idx += 1
        if status != "all":
            where.append(f"al.status = ${idx}")
            params.append(status)
            idx += 1

        count_sql = f"SELECT count(*) FROM audit_log al WHERE {' AND '.join(where)}"
        total = await conn.fetchval(count_sql, *params) or 0
        total_pages = max(1, (total + page_size - 1) // page_size)

        rows_sql = f"""SELECT al.*, a.descriptive_name AS account_name
                       FROM audit_log al LEFT JOIN google_ads_accounts a
                         ON a.customer_id = al.customer_id
                       WHERE {" AND ".join(where)}
                       ORDER BY al.occurred_at DESC LIMIT ${idx} OFFSET ${idx + 1}"""
        params_with_pagination = params + [page_size, offset]
        rows = await conn.fetch(rows_sql, *params_with_pagination)

    # Group by day for sticky day headers
    grouped: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    today = datetime.now(UTC).date()
    for r in rows:
        d = r["occurred_at"].date()
        if d == today:
            label = "Hoje"
        elif d == today - timedelta(days=1):
            label = "Ontem"
        else:
            label = d.strftime("%d/%m/%Y")
        grouped.setdefault(label, []).append(dict(r))

    # Preserve query string for CSV export link
    qparts = []
    if action_type != "all":
        qparts.append(f"action_type={action_type}")
    if customer_id:
        qparts.append(f"customer_id={customer_id}")
    if status != "all":
        qparts.append(f"status={status}")
    qparts.append(f"days={days}")
    query_string = "&".join(qparts)

    return templates.TemplateResponse(
        request,
        "audit.html",
        {
            "current_user": user,
            "grouped": grouped,
            "accessible_accounts": accounts,
            "filter_action_type": action_type,
            "filter_customer_id": customer_id,
            "filter_status": status,
            "filter_days": days,
            "current_page": page,
            "total_pages": total_pages,
            "query_string": query_string,
        },
    )


@router.get("/audit/export.csv", response_model=None)
async def audit_export_csv(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    action_type: str = "all",
    customer_id: str | None = None,
    days: int = 7,
) -> StreamingResponse:
    """Stream CSV export of the gestor's audit log with current filters applied."""
    pool = connection.get_pool()

    async def stream() -> AsyncIterator[bytes]:
        async with pool.acquire() as conn:
            from src.db.repositories import audit_log

            async for line in audit_log.export_csv_rows(
                conn,
                manager_id=user.id,
                customer_id=customer_id,
                action_type=action_type if action_type != "all" else None,
                days=days,
            ):
                yield line.encode("utf-8")

    filename = f"audit-{datetime.now(UTC).strftime('%Y-%m-%d')}.csv"
    return StreamingResponse(
        stream(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/audit/{audit_id}", response_class=HTMLResponse)
async def audit_detail(
    request: Request,
    audit_id: int,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    """Audit event detail. audit_log.id is BIGSERIAL (int), not UUID."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        from src.db.repositories import audit_log

        # Gestores see only their own; admins see any
        scope_id = None if user.is_admin else user.id
        event = await audit_log.get_by_id(conn, audit_id=audit_id, manager_id=scope_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Audit event not found or out of scope")
    return templates.TemplateResponse(
        request,
        "audit_detail.html",
        {"current_user": user, "event": event},
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

        # Load OAuth connections
        google_conn = await google_oauth_connections.get_active_for_manager(conn, user.id)
        meta_conn = await meta_oauth_connections.get_active_for_manager(conn, user.id)

    # Compute meta token expiry signals
    meta_token_expiring_soon = False
    meta_days_until_expiry: int | None = None
    if meta_conn is not None:
        delta = meta_conn.token_expires_at - datetime.now(UTC)
        meta_days_until_expiry = max(0, delta.days)
        meta_token_expiring_soon = delta.days < 7

    meta_connected = request.query_params.get("meta_connected") == "1"
    meta_revoked = request.query_params.get("meta_revoked") == "1"
    meta_refreshed = request.query_params.get("meta_refreshed") == "1"

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
            "google_conn": google_conn,
            "meta_conn": meta_conn,
            "meta_token_expiring_soon": meta_token_expiring_soon,
            "meta_days_until_expiry": meta_days_until_expiry,
            "meta_connected": meta_connected,
            "meta_revoked": meta_revoked,
            "meta_refreshed": meta_refreshed,
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
            "SELECT id, email, full_name, role, is_active, status, created_at, last_seen_at FROM managers ORDER BY email"
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
    mccs = sorted({a.mcc_id for a in accs if a.mcc_id})
    pending = await pending_invites_count()
    return templates.TemplateResponse(
        request,
        "admin/accounts.html",
        {
            "current_user": user,
            "accounts": accs,
            "mccs": mccs,
            "pending_invites_count": pending,
        },
    )


@router.get("/admin/accounts/meta", response_class=HTMLResponse)
async def admin_accounts_meta(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        accounts = await meta_ad_accounts.list_all(conn)
    pending = await pending_invites_count()
    token_configured = bool(get_settings().meta_system_user_token)
    return templates.TemplateResponse(
        request,
        "admin/accounts_meta.html",
        {
            "current_user": user,
            "accounts": accounts,
            "token_configured": token_configured,
            "pending_invites_count": pending,
        },
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
            "SELECT id, email, full_name, role FROM managers WHERE is_active = true ORDER BY email"
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


@router.get("/admin/access/meta", response_class=HTMLResponse)
async def admin_access_meta(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        managers_rows = await conn.fetch(
            "SELECT id, email, full_name, role FROM managers WHERE is_active = true ORDER BY email"
        )
        accounts = await meta_ad_accounts.list_all(conn)
        access_rows = await conn.fetch(
            "SELECT manager_id, ad_account_id FROM manager_meta_account_access"
        )
    access_set = {(str(r["manager_id"]), r["ad_account_id"]) for r in access_rows}
    pending = await pending_invites_count()
    return templates.TemplateResponse(
        request,
        "admin/access_meta.html",
        {
            "current_user": user,
            "managers_list": [dict(r) for r in managers_rows],
            "accounts": accounts,
            "access_set": access_set,
            "pending_invites_count": pending,
        },
    )


@router.post("/admin/access/meta/toggle", response_class=HTMLResponse)
async def admin_access_meta_toggle(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    manager_id: str = Form(...),
    ad_account_id: str = Form(...),
) -> HTMLResponse:
    _require_admin(user)
    pool = connection.get_pool()
    target_mid = UUID(manager_id)
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM manager_meta_account_access WHERE manager_id=$1 AND ad_account_id=$2",
            target_mid,
            ad_account_id,
        )
        if exists:
            await manager_meta_account_access.revoke(
                conn, manager_id=target_mid, ad_account_id=ad_account_id
            )
            granted = False
        else:
            await manager_meta_account_access.grant(
                conn,
                manager_id=target_mid,
                ad_account_id=ad_account_id,
                access_level="write",
                granted_by=user.id,
            )
            granted = True
    return HTMLResponse(
        _toggle_checkbox_fragment(
            post_url="/admin/access/meta/toggle",
            vals={"manager_id": manager_id, "ad_account_id": ad_account_id},
            checked=granted,
        )
    )


@router.post("/admin/access/meta/bulk-grant", response_class=HTMLResponse, response_model=None)
async def admin_access_meta_bulk_grant(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    manager_id: str = Form(...),  # noqa: B008
    ad_account_ids: list[str] = Form(...),  # noqa: B008
) -> RedirectResponse:
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        await manager_meta_account_access.bulk_grant(
            conn,
            manager_id=UUID(manager_id),
            ad_account_ids=ad_account_ids,
            granted_by=user.id,
        )
    return RedirectResponse(url="/admin/access/meta", status_code=303)


@router.post("/admin/access/meta/bulk-copy", response_class=HTMLResponse, response_model=None)
async def admin_access_meta_bulk_copy(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    from_manager_id: str = Form(...),
    to_manager_id: str = Form(...),
) -> RedirectResponse:
    _require_admin(user)
    if from_manager_id == to_manager_id:
        return RedirectResponse(url="/admin/access/meta?error=same_manager", status_code=303)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        await manager_meta_account_access.copy_access(
            conn,
            from_manager_id=UUID(from_manager_id),
            to_manager_id=UUID(to_manager_id),
            granted_by=user.id,
        )
    return RedirectResponse(url="/admin/access/meta", status_code=303)


# IMPORTANT: keep /by-manager BEFORE /{manager_id} (literal must match before the path param).
@router.get("/admin/access/meta/by-manager", response_class=HTMLResponse)
async def admin_access_meta_by_manager(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        managers_with_counts = await conn.fetch(
            """SELECT m.id, m.email, m.full_name,
                      count(mmaa.ad_account_id) AS access_count
               FROM managers m
               LEFT JOIN manager_meta_account_access mmaa ON mmaa.manager_id = m.id
               WHERE m.is_active = true
               GROUP BY m.id ORDER BY m.email"""
        )
        total_accounts = await conn.fetchval("SELECT count(*) FROM meta_ad_accounts") or 0
        pending = await pending_invites_count()
    return templates.TemplateResponse(
        request,
        "admin/access_by_manager_meta.html",
        {
            "current_user": user,
            "managers_with_counts": [dict(r) for r in managers_with_counts],
            "total_accounts": total_accounts,
            "pending_invites_count": pending,
        },
    )


@router.get("/admin/access/meta/{manager_id}", response_class=HTMLResponse)
async def admin_access_meta_manager_detail(
    request: Request,
    manager_id: str,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    _require_admin(user)
    try:
        parsed_manager_id = UUID(manager_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Gestor not found") from None
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mgr_row = await conn.fetchrow(
            "SELECT id, email, full_name FROM managers WHERE id = $1", parsed_manager_id
        )
        if mgr_row is None:
            raise HTTPException(status_code=404, detail="Gestor not found")
        accs = await meta_ad_accounts.list_all(conn)
        access_rows = await conn.fetch(
            "SELECT ad_account_id FROM manager_meta_account_access WHERE manager_id = $1",
            parsed_manager_id,
        )
        access_set = {r["ad_account_id"] for r in access_rows}
        pending = await pending_invites_count()
    return templates.TemplateResponse(
        request,
        "admin/access_manager_detail_meta.html",
        {
            "current_user": user,
            "manager": dict(mgr_row),
            "accounts": accs,
            "access_set": access_set,
            "pending_invites_count": pending,
        },
    )


@router.post("/admin/access/bulk-grant", response_class=HTMLResponse, response_model=None)
async def admin_access_bulk_grant(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    manager_id: str = Form(...),  # noqa: B008
    customer_ids: list[str] = Form(...),  # noqa: B008
) -> RedirectResponse:
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        await manager_account_access.bulk_grant(
            conn,
            manager_id=UUID(manager_id),
            customer_ids=customer_ids,
            granted_by=user.id,
        )
    return RedirectResponse(url="/admin/access", status_code=303)


@router.post("/admin/access/bulk-copy", response_class=HTMLResponse, response_model=None)
async def admin_access_bulk_copy(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    from_manager_id: str = Form(...),
    to_manager_id: str = Form(...),
) -> RedirectResponse:
    _require_admin(user)
    if from_manager_id == to_manager_id:
        return RedirectResponse(url="/admin/access?error=same_manager", status_code=303)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        await manager_account_access.copy_access(
            conn,
            from_manager_id=UUID(from_manager_id),
            to_manager_id=UUID(to_manager_id),
            granted_by=user.id,
        )
    return RedirectResponse(url="/admin/access", status_code=303)


@router.get("/admin/access/by-manager", response_class=HTMLResponse)
async def admin_access_by_manager(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        managers_with_counts = await conn.fetch(
            """SELECT m.id, m.email, m.full_name,
                      count(maa.customer_id) AS access_count
               FROM managers m
               LEFT JOIN manager_account_access maa ON maa.manager_id = m.id
               WHERE m.is_active = true
               GROUP BY m.id ORDER BY m.email"""
        )
        total_accounts = await conn.fetchval("SELECT count(*) FROM google_ads_accounts") or 0
        pending = await pending_invites_count()
    return templates.TemplateResponse(
        request,
        "admin/access_by_manager.html",
        {
            "current_user": user,
            "managers_with_counts": [dict(r) for r in managers_with_counts],
            "total_accounts": total_accounts,
            "pending_invites_count": pending,
        },
    )


@router.get("/admin/access/{manager_id}", response_class=HTMLResponse)
async def admin_access_manager_detail(
    request: Request,
    manager_id: str,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    _require_admin(user)
    try:
        parsed_manager_id = UUID(manager_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Gestor not found") from None
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mgr_row = await conn.fetchrow(
            "SELECT id, email, full_name FROM managers WHERE id = $1", parsed_manager_id
        )
        if mgr_row is None:
            raise HTTPException(status_code=404, detail="Gestor not found")
        accs = await google_ads_accounts.list_all(conn)
        access_rows = await conn.fetch(
            "SELECT customer_id FROM manager_account_access WHERE manager_id = $1",
            parsed_manager_id,
        )
        access_set = {r["customer_id"] for r in access_rows}
        pending = await pending_invites_count()
    return templates.TemplateResponse(
        request,
        "admin/access_manager_detail.html",
        {
            "current_user": user,
            "manager": dict(mgr_row),
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
    return HTMLResponse(
        _toggle_checkbox_fragment(
            post_url="/admin/access/toggle",
            vals={"manager_id": manager_id, "customer_id": customer_id},
            checked=granted,
        )
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
    try:
        parsed_invite_id = UUID(invite_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Não encontrado") from None
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        from src.db.repositories import managers as managers_repo

        await managers_repo.delete_invite(conn, manager_id=parsed_invite_id)
    # HTMX swap: remove the row by returning empty content
    return HTMLResponse("")


@router.get("/admin/audit", response_class=HTMLResponse)
async def admin_audit(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    manager_id: str | None = None,
    customer_id: str | None = None,
    action_type: str = "all",
    status: str = "all",
    days: int = 7,
    page: int = 1,
) -> HTMLResponse:
    _require_admin(user)

    page_size = 50
    offset = (page - 1) * page_size

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        where = ["al.occurred_at > now() - ($1 || ' days')::interval"]
        params: list[Any] = [str(days)]
        idx = 2
        if manager_id:
            where.append(f"al.manager_id = ${idx}")
            params.append(UUID(manager_id))
            idx += 1
        if customer_id:
            where.append(f"al.customer_id = ${idx}")
            params.append(customer_id)
            idx += 1
        if action_type != "all":
            where.append(f"al.action_type = ${idx}")
            params.append(action_type)
            idx += 1
        if status != "all":
            where.append(f"al.status = ${idx}")
            params.append(status)
            idx += 1

        count_sql = f"SELECT count(*) FROM audit_log al WHERE {' AND '.join(where)}"
        total = await conn.fetchval(count_sql, *params) or 0
        total_pages = max(1, (total + page_size - 1) // page_size)

        rows_sql = f"""SELECT al.id, al.occurred_at, al.action_type, al.operation,
                              al.customer_id, al.target_count, al.status, al.duration_ms,
                              m.email AS manager_email,
                              gaa.descriptive_name AS account_name
                       FROM audit_log al
                       LEFT JOIN managers m ON m.id = al.manager_id
                       LEFT JOIN google_ads_accounts gaa ON gaa.customer_id = al.customer_id
                       WHERE {" AND ".join(where)}
                       ORDER BY al.occurred_at DESC LIMIT ${idx} OFFSET ${idx + 1}"""
        params_with_pagination = params + [page_size, offset]
        rows = await conn.fetch(rows_sql, *params_with_pagination)

        managers_rows = await conn.fetch(
            "SELECT id, email FROM managers WHERE is_active = true ORDER BY email"
        )
        accs = await google_ads_accounts.list_all(conn)

    # Build query_string for CSV export link
    qparts = []
    if manager_id:
        qparts.append(f"manager_id={manager_id}")
    if customer_id:
        qparts.append(f"customer_id={customer_id}")
    if action_type != "all":
        qparts.append(f"action_type={action_type}")
    if status != "all":
        qparts.append(f"status={status}")
    qparts.append(f"days={days}")
    query_string = "&".join(qparts)

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
            "filter_status": status,
            "filter_days": days,
            "current_page": page,
            "total_pages": total_pages,
            "query_string": query_string,
            "pending_invites_count": pending,
        },
    )


@router.get("/admin/audit/export.csv", response_model=None)
async def admin_audit_export_csv(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    manager_id: str | None = None,
    action_type: str = "all",
    customer_id: str | None = None,
    days: int = 7,
) -> StreamingResponse:
    """Stream CSV export of the global audit log (admin) with current filters applied."""
    _require_admin(user)
    pool = connection.get_pool()
    scope_manager_id = UUID(manager_id) if manager_id else None

    async def stream() -> AsyncIterator[bytes]:
        async with pool.acquire() as conn:
            from src.db.repositories import audit_log

            async for line in audit_log.export_csv_rows(
                conn,
                manager_id=scope_manager_id,
                customer_id=customer_id,
                action_type=action_type if action_type != "all" else None,
                days=days,
            ):
                yield line.encode("utf-8")

    filename = f"audit-admin-{datetime.now(UTC).strftime('%Y-%m-%d')}.csv"
    return StreamingResponse(
        stream(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
