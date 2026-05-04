"""Web panel routes."""

from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.auth.panel_session import PANEL_SESSION_COOKIE_NAME
from src.db import connection
from src.db.repositories import (
    google_oauth_connections,
    manager_account_access,
    mcp_sessions,
)
from src.web.deps import (
    CurrentUser,
    current_manager,
    optional_current_manager,
)

log = structlog.get_logger(__name__)

router = APIRouter(tags=["web"])

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
