"""CRUD for `meta_oauth_connections` — Meta Ads OAuth tokens.

Diferente de google_oauth_connections: Meta usa long-lived access_token
(~60 dias) em vez de refresh_token. token_expires_at é NOT NULL para
permitir job background avisar gestor antes de expirar.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import asyncpg


@dataclass(slots=True, frozen=True)
class MetaOAuthConnection:
    id: UUID
    manager_id: UUID
    fb_user_id: str
    fb_email: str
    access_token_enc: bytes
    token_expires_at: datetime
    scopes: list[str]
    connected_at: datetime
    revoked_at: datetime | None


def _row_to_conn(row: asyncpg.Record) -> MetaOAuthConnection:
    return MetaOAuthConnection(
        id=row["id"],
        manager_id=row["manager_id"],
        fb_user_id=row["fb_user_id"],
        fb_email=row["fb_email"],
        access_token_enc=row["access_token_enc"],
        token_expires_at=row["token_expires_at"],
        scopes=row["scopes"],
        connected_at=row["connected_at"],
        revoked_at=row["revoked_at"],
    )


async def upsert(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    fb_user_id: str,
    fb_email: str,
    access_token_enc: bytes,
    token_expires_at: datetime,
    scopes: list[str],
) -> MetaOAuthConnection:
    """INSERT new connection or update access_token if (manager_id, fb_user_id) exists."""
    row = await conn.fetchrow(
        """
        INSERT INTO meta_oauth_connections
            (manager_id, fb_user_id, fb_email, access_token_enc, token_expires_at, scopes)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (manager_id, fb_user_id) DO UPDATE SET
            fb_email = EXCLUDED.fb_email,
            access_token_enc = EXCLUDED.access_token_enc,
            token_expires_at = EXCLUDED.token_expires_at,
            scopes = EXCLUDED.scopes,
            connected_at = now(),
            revoked_at = NULL
        RETURNING *
        """,
        manager_id,
        fb_user_id,
        fb_email,
        access_token_enc,
        token_expires_at,
        scopes,
    )
    assert row is not None
    return _row_to_conn(row)


async def get_active_for_manager(
    conn: asyncpg.Connection, manager_id: UUID
) -> MetaOAuthConnection | None:
    """Return the most recent NON-REVOKED connection for the manager."""
    row = await conn.fetchrow(
        """
        SELECT * FROM meta_oauth_connections
        WHERE manager_id = $1 AND revoked_at IS NULL
        ORDER BY connected_at DESC
        LIMIT 1
        """,
        manager_id,
    )
    return _row_to_conn(row) if row else None


async def revoke(conn: asyncpg.Connection, connection_id: UUID) -> None:
    await conn.execute(
        "UPDATE meta_oauth_connections SET revoked_at = now() WHERE id = $1",
        connection_id,
    )
