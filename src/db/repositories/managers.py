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


def _row_to_manager(row: asyncpg.Record) -> Manager:
    return Manager(
        id=row["id"],
        email=row["email"],
        full_name=row["full_name"],
        role=row["role"],
        is_active=row["is_active"],
        created_at=row["created_at"],
        last_seen_at=row["last_seen_at"],
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
