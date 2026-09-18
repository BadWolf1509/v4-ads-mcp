"""Login, logout e sessões MCP do gestor.

Também aqui: o dashboard (`/`) e as páginas públicas (help, legal/*,
access-denied) — nenhuma tem responsabilidade própria na tabela de dez módulos
do brief da Task 2, e este é o módulo mais próximo em espírito (entrada do
painel / auth, sem escopo admin). Ver o relatório da Task 2 para a decisão.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from src.auth.panel_session import PANEL_SESSION_COOKIE_NAME
from src.auth.sessions import generate_session_token, hash_session_token
from src.config import get_settings
from src.db import connection
from src.db.repositories import google_oauth_connections, manager_account_access, mcp_sessions
from src.db.repositories.mcp_sessions import DEFAULT_TTL_DAYS
from src.web.deps import CurrentUser, current_manager, optional_current_manager
from src.web.routes._shared import templates

router = APIRouter(tags=["web"])


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
    # mcp_url injetado no contexto (não hardcoded no template) pra os snippets de
    # conexão nunca driftarem da URL real do serviço — mesmo padrão do /sessions.
    mcp_url = f"{get_settings().public_base_url}/mcp"
    return templates.TemplateResponse(
        request, "help.html", {"current_user": user, "mcp_url": mcp_url}
    )


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


@router.get("/sessions", response_class=HTMLResponse)
async def sessions_list(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    include_revoked: bool = False,
) -> HTMLResponse:
    """List manager's MCP sessions."""
    # F76/F77/F91 — leitura idempotente, sobrevive a reconexão (Task 6, PR 5).
    sessions = await connection.run_with_reconnect(
        lambda conn: mcp_sessions.list_for_manager(conn, user.id, include_revoked=include_revoked)
    )

    return templates.TemplateResponse(
        request,
        "sessions/list.html",
        {
            "current_user": user,
            "sessions": sessions,
            "include_revoked": include_revoked,
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
    # F76/F77/F91 — leitura idempotente, sobrevive a reconexão (Task 6, PR 5).
    session = await connection.run_with_reconnect(
        lambda conn: mcp_sessions.get_by_id(
            conn,
            session_id=parsed_session_id,
            manager_id=user.id,
        )
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

    _toast_trigger = '{"toast": {"message": "Sessão revogada.", "kind": "success"}}'

    # If HTMX request, decide by the originating page.
    # Detail page (/sessions/<id>) → send HX-Redirect so HTMX navigates cleanly.
    # List page (/sessions) → swap table fragment in-place (existing behaviour).
    is_htmx = request.headers.get("HX-Request") == "true"
    if is_htmx:
        current_url = request.headers.get("HX-Current-URL", "")
        current_path = urlparse(current_url).path
        if current_path.startswith("/sessions/") and current_path.rstrip("/") != "/sessions":
            # Came from the detail page — redirect without flashing the fragment.
            return Response(
                status_code=204,
                headers={"HX-Redirect": "/sessions", "HX-Trigger": _toast_trigger},
            )
        # Came from the list page — return fresh table fragment for in-place swap.
        # Preserve include_revoked from the originating page's query string.
        qs = parse_qs(urlparse(current_url).query)
        include_revoked = qs.get("include_revoked", ["0"])[0] in ("1", "true", "True")
        # F76/F77/F91 — leitura idempotente e independente da revogação acima
        # (já commitada quando o bloco de acquire dela fechou): sobrevive a
        # reconexão (Task 6, PR 5).
        sessions = await connection.run_with_reconnect(
            lambda conn: mcp_sessions.list_for_manager(
                conn, user.id, include_revoked=include_revoked
            )
        )
        resp = templates.TemplateResponse(
            request,
            "sessions/_table.html",
            {"current_user": user, "sessions": sessions, "include_revoked": include_revoked},
        )
        resp.headers["HX-Trigger"] = _toast_trigger
        return resp
    # Sem HTMX: POST-redirect-GET. Renderizar a lista com 200 faria o refresh
    # re-executar a revogacao e sujaria o historico.
    return RedirectResponse(url="/sessions", status_code=303)
