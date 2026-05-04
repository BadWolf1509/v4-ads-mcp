"""Append-only audit log writes."""

from typing import Any
from uuid import UUID

import asyncpg


async def record(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID | None,
    session_id: UUID | None,
    customer_id: str | None,
    action_type: str,  # 'mutate' | 'read' | 'auth' | 'system'
    operation: str,
    target_count: int | None = None,
    params_summary: dict[str, Any] | None = None,
    google_request_id: str | None = None,
    status: str = "success",  # 'success' | 'error' | 'denied'
    error_message: str | None = None,
    duration_ms: int | None = None,
) -> int:
    """Insert a row into audit_log; returns the new row id."""
    import json

    row = await conn.fetchrow(
        """
        INSERT INTO audit_log (
            manager_id, session_id, customer_id,
            action_type, operation, target_count,
            params_summary, google_request_id, status,
            error_message, duration_ms
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $10, $11)
        RETURNING id
        """,
        manager_id,
        session_id,
        customer_id,
        action_type,
        operation,
        target_count,
        json.dumps(params_summary) if params_summary is not None else None,
        google_request_id,
        status,
        error_message,
        duration_ms,
    )
    assert row is not None
    return int(row["id"])
