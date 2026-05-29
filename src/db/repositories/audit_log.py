"""Append-only audit log writes."""

import csv
import io
from collections.abc import AsyncIterator
from typing import Any, Literal
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
    provider_request_id: str | None = None,
    status: str = "success",  # 'success' | 'error' | 'denied'
    error_message: str | None = None,
    duration_ms: int | None = None,
    platform: Literal["google", "meta"] = "google",
) -> int:
    """Insert a row into audit_log; returns the new row id.

    platform: 'google' (default, preserves existing callers) | 'meta'.
    """
    import json

    row = await conn.fetchrow(
        """
        INSERT INTO audit_log (
            manager_id, session_id, customer_id,
            action_type, operation, target_count,
            params_summary, provider_request_id, status,
            error_message, duration_ms, platform
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $10, $11, $12)
        RETURNING id
        """,
        manager_id,
        session_id,
        customer_id,
        action_type,
        operation,
        target_count,
        json.dumps(params_summary) if params_summary is not None else None,
        provider_request_id,
        status,
        error_message,
        duration_ms,
        platform,
    )
    assert row is not None
    return int(row["id"])


async def get_by_id(
    conn: asyncpg.Connection,
    *,
    audit_id: int,
    manager_id: UUID | None,
) -> dict[str, Any] | None:
    """Fetch a single audit event by its BIGSERIAL id.

    If manager_id is provided, scoped to that gestor (returns None if event belongs to another).
    If manager_id is None (admin context), returns any event by id.
    """
    if manager_id is None:
        row = await conn.fetchrow(
            """SELECT al.*, m.email AS manager_email,
                      s.label AS session_label,
                      a.descriptive_name AS account_name
               FROM audit_log al
               LEFT JOIN managers m ON m.id = al.manager_id
               LEFT JOIN mcp_sessions s ON s.id = al.session_id
               LEFT JOIN google_ads_accounts a ON a.customer_id = al.customer_id
               WHERE al.id = $1""",
            audit_id,
        )
    else:
        row = await conn.fetchrow(
            """SELECT al.*, m.email AS manager_email,
                      s.label AS session_label,
                      a.descriptive_name AS account_name
               FROM audit_log al
               LEFT JOIN managers m ON m.id = al.manager_id
               LEFT JOIN mcp_sessions s ON s.id = al.session_id
               LEFT JOIN google_ads_accounts a ON a.customer_id = al.customer_id
               WHERE al.id = $1 AND al.manager_id = $2""",
            audit_id,
            manager_id,
        )
    return dict(row) if row else None


async def summary_stats(conn: asyncpg.Connection) -> dict[str, int]:
    """Aggregate counts over the last 24 hours."""
    row = await conn.fetchrow(
        """SELECT
             count(*) AS total,
             count(*) FILTER (WHERE status = 'success') AS success,
             count(*) FILTER (WHERE status = 'error') AS errors
           FROM audit_log
           WHERE occurred_at > now() - interval '24 hours'"""
    )
    return {
        "total_24h": row["total"],
        "success_24h": row["success"],
        "errors_24h": row["errors"],
    }


async def export_csv_rows(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID | None = None,
    customer_id: str | None = None,
    action_type: str | None = None,
    status: str | None = None,
    days: int = 7,
) -> AsyncIterator[str]:
    """Yield CSV lines (header + data) for streaming response."""
    # All WHERE clauses qualified with the `al` alias: the SELECT joins `managers m`,
    # which ALSO has a `status` column → unqualified `status` is ambiguous (asyncpg
    # AmbiguousColumnError). Qualify everything for safety/consistency with the SELECT.
    where = ["al.occurred_at > now() - ($1 || ' days')::interval"]
    params: list[Any] = [str(days)]
    idx = 2
    if manager_id is not None:
        where.append(f"al.manager_id = ${idx}")
        params.append(manager_id)
        idx += 1
    if customer_id:
        where.append(f"al.customer_id = ${idx}")
        params.append(customer_id)
        idx += 1
    if action_type and action_type != "all":
        where.append(f"al.action_type = ${idx}")
        params.append(action_type)
        idx += 1
    if status and status != "all":
        where.append(f"al.status = ${idx}")
        params.append(status)
        idx += 1
    sql = f"""SELECT al.occurred_at, m.email, al.operation, al.customer_id,
                     al.action_type, al.status, al.target_count, al.duration_ms,
                     al.error_message, al.provider_request_id
              FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id
              WHERE {" AND ".join(where)}
              ORDER BY al.occurred_at DESC"""

    # Header
    header = [
        "occurred_at",
        "manager_email",
        "operation",
        "customer_id",
        "action_type",
        "status",
        "target_count",
        "duration_ms",
        "error_message",
        "provider_request_id",
    ]
    buf = io.StringIO()
    csv.writer(buf).writerow(header)
    yield buf.getvalue()

    # asyncpg server-side cursors MUST run inside an explicit transaction.
    # (Pre-existing bug surfaced by the first test to actually iterate this
    # generator: NoActiveSQLTransactionError without this wrapper.)
    async with conn.transaction():
        async for row in conn.cursor(sql, *params):
            buf = io.StringIO()
            csv.writer(buf).writerow(
                [
                    row["occurred_at"].isoformat() if row["occurred_at"] else "",
                    row["email"] or "",
                    row["operation"] or "",
                    row["customer_id"] or "",
                    row["action_type"] or "",
                    row["status"] or "",
                    row["target_count"] if row["target_count"] is not None else "",
                    row["duration_ms"] if row["duration_ms"] is not None else "",
                    row["error_message"] or "",
                    row["provider_request_id"] or "",
                ]
            )
            yield buf.getvalue()


async def list_for_manager(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    days: int = 7,
    limit: int = 100,
    customer_id: str | None = None,
    action_type: str | None = None,
) -> list[dict[str, Any]]:
    """Paginated list of audit_log rows scoped to a manager.

    Filters (all optional except manager_id):
    - days: time window (default 7)
    - limit: row cap (default 100, max enforced by caller schema)
    - customer_id: filter by account
    - action_type: filter by 'mutate'/'read'/'auth'/'system'; None or 'all' → no filter

    Returns rows ORDER BY occurred_at DESC, with subset of columns (omits
    params_summary to keep response compact; use get_by_id() for full detail).
    """
    where = ["manager_id = $1", "occurred_at > now() - ($2 || ' days')::interval"]
    params: list[Any] = [manager_id, str(days)]
    idx = 3
    if customer_id:
        where.append(f"customer_id = ${idx}")
        params.append(customer_id)
        idx += 1
    if action_type and action_type != "all":
        where.append(f"action_type = ${idx}")
        params.append(action_type)
        idx += 1
    params.append(limit)
    sql = f"""SELECT id, occurred_at, operation, customer_id, action_type,
                     target_count, status, duration_ms, provider_request_id,
                     error_message, platform
              FROM audit_log
              WHERE {" AND ".join(where)}
              ORDER BY occurred_at DESC
              LIMIT ${idx}"""
    rows = await conn.fetch(sql, *params)
    return [
        {
            "id": int(r["id"]),
            "occurred_at": r["occurred_at"].isoformat() if r["occurred_at"] else None,
            "operation": r["operation"],
            "customer_id": r["customer_id"],
            "action_type": r["action_type"],
            "target_count": int(r["target_count"]) if r["target_count"] is not None else None,
            "status": r["status"],
            "duration_ms": int(r["duration_ms"]) if r["duration_ms"] is not None else None,
            "provider_request_id": r["provider_request_id"],
            "error_message": r["error_message"],
            "platform": r["platform"],
        }
        for r in rows
    ]
