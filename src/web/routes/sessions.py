"""Login, logout e sessões MCP do gestor.

O dashboard (`dashboard.py`) e as páginas públicas (`pages.py`) saíram daqui na
varredura de 11/2026 (Task F6).
"""

from urllib.parse import parse_qs, urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from src.auth.panel_session import PANEL_SESSION_COOKIE_NAME
from src.auth.sessions import generate_session_token, hash_session_token
from src.config import get_settings
from src.db import connection
from src.db.repositories import mcp_sessions
from src.db.repositories.mcp_sessions import DEFAULT_TTL_DAYS
from src.web.deps import CurrentUser, current_manager, optional_current_manager
from src.web.routes._shared import eh_htmx, resposta_hx, templates, toast_trigger

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
            raise HTTPException(status_code=404, detail="Sessão não encontrada")
        if target.revoked_at is None:
            await mcp_sessions.revoke(conn, session_id)

    _toast_trigger = toast_trigger("Sessão revogada.")

    # If HTMX request, decide by the originating page.
    # Detail page (/sessions/<id>) → send HX-Redirect so HTMX navigates cleanly.
    # List page (/sessions) → swap table fragment in-place (existing behaviour).
    if eh_htmx(request):
        current_url = request.headers.get("HX-Current-URL", "")
        current_path = urlparse(current_url).path
        if current_path.startswith("/sessions/") and current_path.rstrip("/") != "/sessions":
            # Came from the detail page — redirect without flashing the fragment.
            return resposta_hx(
                request, destino="/sessions", hx="redirect", toast="Sessão revogada."
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
