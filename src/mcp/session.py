"""MCP session resolution from Bearer tokens.

Fetches the session row from `mcp_sessions` keyed by SHA-256 of the
Bearer token, validates not-revoked + not-expired, and binds the
manager_id/session_id to the request context. Updates last_used_at
asynchronously after the resolution.
"""

import structlog

from src.auth.sessions import hash_session_token
from src.db import connection
from src.db.repositories import managers, mcp_sessions
from src.mcp.context import McpRequestContext, set_current

log = structlog.get_logger(__name__)


def extract_bearer_token(authorization_header: str | None) -> str | None:
    """Parse 'Bearer <token>' header, returning the token or None."""
    if not authorization_header:
        return None
    parts = authorization_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


class UnauthorizedError(Exception):
    """Raised when Bearer is missing/invalid/expired/revoked."""


async def resolve_session_to_context(authorization_header: str | None) -> McpRequestContext:
    """Resolve Bearer header → bind request context. Raises UnauthorizedError on failure."""
    token = extract_bearer_token(authorization_header)
    if token is None:
        raise UnauthorizedError("Missing or malformed Authorization Bearer header")

    token_hash = hash_session_token(token)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        session = await mcp_sessions.find_by_hash(conn, token_hash)
        if session is None:
            raise UnauthorizedError("Session not found, expired, or revoked")
        m = await managers.get_by_id(conn, session.manager_id)
        if m is None or not m.is_active:
            raise UnauthorizedError("Manager inactive or not found")
        # Touch last_used_at + manager.last_seen_at in same connection.
        await mcp_sessions.touch_last_used(conn, session.id)
        await managers.touch_last_seen(conn, session.manager_id)

    ctx = McpRequestContext(manager_id=session.manager_id, session_id=session.id)
    set_current(ctx)
    log.info("mcp_session_resolved", manager_id=str(ctx.manager_id), session_id=str(ctx.session_id))
    return ctx
