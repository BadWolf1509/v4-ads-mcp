"""Tests for audit_log repository extensions (Phase 4)."""

from datetime import datetime, timedelta  # noqa: F401
from uuid import uuid4

import pytest

from src.db.repositories import audit_log


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_by_id_returns_full_row(db):
    mid = uuid4()
    sid = uuid4()
    pool = db
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO managers (id, email, status, role) VALUES ($1, 'a@v4company.com', 'active', 'gestor')""",
            mid,
        )
        await conn.execute(
            """INSERT INTO mcp_sessions (id, manager_id, label, token_hash) VALUES ($1, $2, 'test', 'h')""",
            sid,
            mid,
        )
        # audit_log.id is BIGSERIAL — let DB generate, capture via RETURNING.
        aid = await conn.fetchval(
            """INSERT INTO audit_log (manager_id, session_id, customer_id, action_type, operation, status,
                                       target_count, params_summary, error_message, duration_ms, occurred_at)
               VALUES ($1, $2, '1234567890', 'read', 'list_my_accounts', 'success',
                       23, '{}'::jsonb, NULL, 7, now())
               RETURNING id""",
            mid,
            sid,
        )
        result = await audit_log.get_by_id(conn, audit_id=aid, manager_id=mid)
    assert result is not None
    assert result["operation"] == "list_my_accounts"
    assert result["target_count"] == 23


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_by_id_scopes_to_manager(db):
    """Gestor passing manager_id can't see other gestores' events."""
    mid = uuid4()
    other = uuid4()
    pool = db
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO managers (id, email, status, role) VALUES
               ($1, 'a@v4company.com', 'active', 'gestor'),
               ($2, 'b@v4company.com', 'active', 'gestor')""",
            mid,
            other,
        )
        aid = await conn.fetchval(
            """INSERT INTO audit_log (manager_id, action_type, operation, status, occurred_at)
               VALUES ($1, 'read', 'op', 'success', now())
               RETURNING id""",
            other,  # belongs to OTHER manager
        )
        result = await audit_log.get_by_id(conn, audit_id=aid, manager_id=mid)
    assert result is None  # mid can't see other's row


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_by_id_admin_sees_any(db):
    """When manager_id=None (admin context), any audit_id is reachable."""
    other = uuid4()
    pool = db
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO managers (id, email, status, role) VALUES ($1, 'b@v4company.com', 'active', 'gestor')""",
            other,
        )
        aid = await conn.fetchval(
            """INSERT INTO audit_log (manager_id, action_type, operation, status, occurred_at)
               VALUES ($1, 'read', 'op', 'success', now())
               RETURNING id""",
            other,
        )
        result = await audit_log.get_by_id(conn, audit_id=aid, manager_id=None)
    assert result is not None
    assert result["operation"] == "op"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_summary_stats_24h_window(db):
    mid = uuid4()
    pool = db
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO managers (id, email, status, role) VALUES ($1, 'a@v4company.com', 'active', 'gestor')""",
            mid,
        )
        # 2 success in last hour, 1 error in last hour, 1 success 25h ago (out of window)
        await conn.execute(
            """INSERT INTO audit_log (manager_id, action_type, operation, status, occurred_at) VALUES
               ($1, 'read', 'op1', 'success', now() - interval '10 minutes'),
               ($1, 'read', 'op1', 'success', now() - interval '20 minutes'),
               ($1, 'mutate', 'op2', 'error', now() - interval '5 minutes'),
               ($1, 'read', 'op1', 'success', now() - interval '25 hours')""",
            mid,
        )
        stats = await audit_log.summary_stats(conn)
    assert stats["total_24h"] == 3
    assert stats["errors_24h"] == 1
    assert stats["success_24h"] == 2
