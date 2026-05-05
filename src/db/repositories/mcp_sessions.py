"""CRUD for `mcp_sessions`."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

DEFAULT_TTL_DAYS = 90


@dataclass(slots=True, frozen=True)
class McpSession:
    id: UUID
    manager_id: UUID
    token_hash: str
    label: str | None
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
    expires_at: datetime | None


def _row_to_session(row: asyncpg.Record) -> McpSession:
    return McpSession(
        id=row["id"],
        manager_id=row["manager_id"],
        token_hash=row["token_hash"],
        label=row["label"],
        created_at=row["created_at"],
        last_used_at=row["last_used_at"],
        revoked_at=row["revoked_at"],
        expires_at=row["expires_at"],
    )


async def create(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    token_hash: str,
    label: str | None,
    ttl_days: int = DEFAULT_TTL_DAYS,
) -> McpSession:
    row = await conn.fetchrow(
        """
        INSERT INTO mcp_sessions (manager_id, token_hash, label, expires_at)
        VALUES ($1, $2, $3, now() + ($4 || ' days')::interval)
        RETURNING *
        """,
        manager_id,
        token_hash,
        label,
        str(ttl_days),
    )
    assert row is not None
    return _row_to_session(row)


async def find_by_hash(conn: asyncpg.Connection, token_hash: str) -> McpSession | None:
    """Return only if NOT revoked AND NOT expired."""
    row = await conn.fetchrow(
        """
        SELECT * FROM mcp_sessions
        WHERE token_hash = $1
          AND revoked_at IS NULL
          AND (expires_at IS NULL OR expires_at > now())
        """,
        token_hash,
    )
    return _row_to_session(row) if row else None


async def touch_last_used(conn: asyncpg.Connection, session_id: UUID) -> None:
    await conn.execute(
        "UPDATE mcp_sessions SET last_used_at = now() WHERE id = $1",
        session_id,
    )


async def revoke(conn: asyncpg.Connection, session_id: UUID) -> None:
    await conn.execute(
        "UPDATE mcp_sessions SET revoked_at = now() WHERE id = $1 AND revoked_at IS NULL",
        session_id,
    )


async def list_for_manager(
    conn: asyncpg.Connection, manager_id: UUID, *, include_revoked: bool = False
) -> list[McpSession]:
    if include_revoked:
        rows = await conn.fetch(
            "SELECT * FROM mcp_sessions WHERE manager_id = $1 ORDER BY created_at DESC",
            manager_id,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT * FROM mcp_sessions
            WHERE manager_id = $1 AND revoked_at IS NULL
            ORDER BY created_at DESC
            """,
            manager_id,
        )
    return [_row_to_session(r) for r in rows]


async def get_by_id(
    conn: asyncpg.Connection,
    *,
    session_id: UUID,
    manager_id: UUID,
) -> dict[str, Any] | None:
    """Fetch one session, scoped to the owning manager. Returns None if not found or not owned."""
    row = await conn.fetchrow(
        """SELECT id, manager_id, label, created_at, last_used_at, expires_at, revoked_at
           FROM mcp_sessions
           WHERE id = $1 AND manager_id = $2""",
        session_id,
        manager_id,
    )
    return dict(row) if row else None
