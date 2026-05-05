"""CRUD for the `managers` table."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import asyncpg


@dataclass(slots=True, frozen=True)
class Manager:
    id: UUID
    email: str
    full_name: str | None
    role: str  # 'gestor' | 'admin'
    is_active: bool
    created_at: datetime
    last_seen_at: datetime | None
    status: str  # 'invited' | 'active' | 'inactive' (added in migration 002)
    invited_by: UUID | None  # added in migration 002
    invited_at: datetime | None  # added in migration 002


def _row_to_manager(row: asyncpg.Record) -> Manager:
    return Manager(
        id=row["id"],
        email=row["email"],
        full_name=row["full_name"],
        role=row["role"],
        is_active=row["is_active"],
        created_at=row["created_at"],
        last_seen_at=row["last_seen_at"],
        status=row["status"],
        invited_by=row["invited_by"],
        invited_at=row["invited_at"],
    )


async def get_by_id(conn: asyncpg.Connection, manager_id: UUID) -> Manager | None:
    row = await conn.fetchrow("SELECT * FROM managers WHERE id = $1", manager_id)
    return _row_to_manager(row) if row else None


async def get_by_email(conn: asyncpg.Connection, email: str) -> Manager | None:
    row = await conn.fetchrow("SELECT * FROM managers WHERE email = $1", email)
    return _row_to_manager(row) if row else None


async def create(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    email: str,
    full_name: str | None,
    role: str = "gestor",
) -> Manager:
    row = await conn.fetchrow(
        """
        INSERT INTO managers (id, email, full_name, role)
        VALUES ($1, $2, $3, $4)
        RETURNING *
        """,
        manager_id,
        email,
        full_name,
        role,
    )
    assert row is not None
    return _row_to_manager(row)


async def touch_last_seen(conn: asyncpg.Connection, manager_id: UUID) -> None:
    await conn.execute(
        "UPDATE managers SET last_seen_at = now() WHERE id = $1",
        manager_id,
    )


async def list_active(conn: asyncpg.Connection) -> list[Manager]:
    rows = await conn.fetch("SELECT * FROM managers WHERE is_active = true ORDER BY email")
    return [_row_to_manager(r) for r in rows]


async def create_invited(
    conn: asyncpg.Connection,
    *,
    email: str,
    invited_by: UUID,
    full_name: str | None = None,
) -> Manager:
    """Pre-create a manager row with status='invited' before they log in.

    Raises asyncpg.UniqueViolationError if email already exists in managers.
    """
    from uuid import uuid4

    row = await conn.fetchrow(
        """
        INSERT INTO managers (id, email, full_name, role, status, is_active, invited_by, invited_at)
        VALUES ($1, $2, $3, 'gestor', 'invited', true, $4, $5)
        RETURNING *
        """,
        uuid4(),
        email,
        full_name,
        invited_by,
        datetime.utcnow(),
    )
    assert row is not None
    return _row_to_manager(row)


async def mark_active(conn: asyncpg.Connection, *, manager_id: UUID) -> bool:
    """Flip status from 'invited' to 'active'. Returns True if a row was modified.

    Does NOT promote 'inactive' to 'active' — that requires explicit admin action.
    """
    result = await conn.execute(
        "UPDATE managers SET status = 'active' WHERE id = $1 AND status = 'invited'",
        manager_id,
    )
    # asyncpg returns 'UPDATE n' where n is row count
    return bool(result.endswith(" 1"))


async def list_invited(conn: asyncpg.Connection) -> list[Manager]:
    """All managers awaiting first OAuth login (status='invited')."""
    rows = await conn.fetch(
        "SELECT * FROM managers WHERE status = 'invited' ORDER BY invited_at DESC"
    )
    return [_row_to_manager(r) for r in rows]


async def delete_invite(conn: asyncpg.Connection, *, manager_id: UUID) -> bool:
    """Remove an invited row before the user logs in. Returns True if deleted.

    Safe: only deletes when status='invited'. Active/inactive rows are not affected.
    """
    result = await conn.execute(
        "DELETE FROM managers WHERE id = $1 AND status = 'invited'",
        manager_id,
    )
    return bool(result.endswith(" 1"))


async def count_invited(conn: asyncpg.Connection) -> int:
    """Count of managers awaiting first login. Used by /admin sub-nav badge."""
    n = await conn.fetchval("SELECT count(*) FROM managers WHERE status = 'invited'")
    return n or 0


async def count_all(conn: asyncpg.Connection) -> int:
    """Total managers (any status). Used by OAuth bootstrap path."""
    n = await conn.fetchval("SELECT count(*) FROM managers")
    return n or 0
