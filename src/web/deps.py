"""FastAPI dependencies for panel routes."""

from uuid import UUID

import structlog
from fastapi import HTTPException, Request, status

from src.auth.panel_session import (
    PANEL_SESSION_COOKIE_NAME,
    InvalidPanelSessionError,
    PanelSession,
    verify_panel_session,
)
from src.config import get_settings
from src.db import connection
from src.db.repositories import managers
from src.db.repositories.managers import Manager

log = structlog.get_logger(__name__)


class CurrentUser:
    """Wraps a Manager + adds web-friendly accessors (e.g., is_admin)."""

    def __init__(self, manager: Manager):
        self.manager = manager
        self.id = manager.id
        self.email = manager.email
        self.full_name = manager.full_name
        self.role = manager.role
        self.is_admin = manager.role == "admin"
        self.is_active = manager.is_active
        self.last_seen_at = manager.last_seen_at


async def _resolve_session(request: Request) -> PanelSession | None:
    cookie = request.cookies.get(PANEL_SESSION_COOKIE_NAME)
    if not cookie:
        return None
    settings = get_settings()
    try:
        return verify_panel_session(cookie, settings.session_signing_key, aud="panel")
    except InvalidPanelSessionError as e:
        log.info("panel_session_invalid", reason=str(e))
        return None


async def current_manager(request: Request) -> CurrentUser:
    """Required: 302 to /login if no valid session."""
    session = await _resolve_session(request)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/login"},
        )
    # F91: read idempotente que roda a CADA page-load de um painel de baixo
    # tráfego — o cenário exato do F76 (conexão ociosa que o Supabase fecha).
    # Sem o reconnect, o primeiro acesso da manhã vira 500.
    m = await connection.run_with_reconnect(
        lambda conn: managers.get_by_id(conn, UUID(session.manager_id))
    )
    # F84: predicado unico (is_active E status) — ver Manager.is_deactivated.
    if m is None or m.is_deactivated:
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/login"},
        )
    return CurrentUser(m)


async def optional_current_manager(request: Request) -> CurrentUser | None:
    session = await _resolve_session(request)
    if session is None:
        return None
    m = await connection.run_with_reconnect(  # F91 — ver current_manager
        lambda conn: managers.get_by_id(conn, UUID(session.manager_id))
    )
    # F84: predicado unico (is_active E status) — ver Manager.is_deactivated.
    if m is None or m.is_deactivated:
        return None
    return CurrentUser(m)


async def pending_invites_count() -> int:
    """Real count of managers with status='invited'. Used by /admin sub-nav badge."""
    from src.db import connection
    from src.db.repositories import managers

    # F91 — 11 rotas admin chamam isto; é read puro.
    return await connection.run_with_reconnect(managers.count_invited)
