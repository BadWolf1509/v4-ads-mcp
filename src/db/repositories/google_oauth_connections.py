"""CRUD for `google_oauth_connections`."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import asyncpg


@dataclass(slots=True, frozen=True)
class OAuthConnection:
    id: UUID
    manager_id: UUID
    google_email: str
    refresh_token_enc: bytes
    scopes: list[str]
    connected_at: datetime
    revoked_at: datetime | None


def _row_to_conn(row: asyncpg.Record) -> OAuthConnection:
    return OAuthConnection(
        id=row["id"],
        manager_id=row["manager_id"],
        google_email=row["google_email"],
        refresh_token_enc=row["refresh_token_enc"],
        scopes=row["scopes"],
        connected_at=row["connected_at"],
        revoked_at=row["revoked_at"],
    )


async def upsert(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    google_email: str,
    refresh_token_enc: bytes,
    scopes: list[str],
) -> OAuthConnection:
    """INSERT new connection or update refresh_token if (manager_id, email) exists."""
    row = await conn.fetchrow(
        """
        INSERT INTO google_oauth_connections
            (manager_id, google_email, refresh_token_enc, scopes)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (manager_id, google_email) DO UPDATE SET
            refresh_token_enc = EXCLUDED.refresh_token_enc,
            scopes = EXCLUDED.scopes,
            connected_at = now(),
            revoked_at = NULL
        RETURNING *
        """,
        manager_id,
        google_email,
        refresh_token_enc,
        scopes,
    )
    assert row is not None
    return _row_to_conn(row)


async def get_active_for_manager(
    conn: asyncpg.Connection, manager_id: UUID
) -> OAuthConnection | None:
    """Return the most recent NON-REVOKED connection for the manager."""
    row = await conn.fetchrow(
        """
        SELECT * FROM google_oauth_connections
        WHERE manager_id = $1 AND revoked_at IS NULL
        ORDER BY connected_at DESC
        LIMIT 1
        """,
        manager_id,
    )
    return _row_to_conn(row) if row else None


async def revoke(conn: asyncpg.Connection, connection_id: UUID) -> None:
    await conn.execute(
        "UPDATE google_oauth_connections SET revoked_at = now() WHERE id = $1",
        connection_id,
    )
