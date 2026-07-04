"""Integration tests: src/jobs/purge.py::purge_expired.

Seed de rows velhas + recentes em pending_confirmations/rate_counters/
meta_rate_counters → purge_expired deleta só as velhas, nunca toca audit_log
(compliance — não há assertion de purge nele, propositalmente).
"""

from uuid import uuid4

import pytest

from src.jobs.purge import purge_expired

pytestmark = pytest.mark.asyncio


async def _seed_manager_and_session(conn):
    """pending_confirmations exige FK pra mcp_sessions -> managers."""
    mid = uuid4()
    sid = uuid4()
    await conn.execute(
        "INSERT INTO managers (id, email, status, role) VALUES ($1, 'a@v4company.com', 'active', 'gestor')",
        mid,
    )
    await conn.execute(
        "INSERT INTO mcp_sessions (id, manager_id, label, token_hash) VALUES ($1, $2, 'test', 'h')",
        sid,
        mid,
    )
    return mid, sid


@pytest.mark.integration
async def test_purge_expired_deletes_only_old_pending_confirmations(db):
    pool = db
    async with pool.acquire() as conn:
        _mid, sid = await _seed_manager_and_session(conn)

        # Velha: expirou há mais de 7 dias -> deve ser purgada (consumida ou não).
        await conn.execute(
            """INSERT INTO pending_confirmations
                   (token, session_id, customer_id, operation_type, payload, blast_summary,
                    expires_at, consumed_at)
               VALUES ('old-unconsumed', $1, '1234567890', 'pause_keyword', '{}'::jsonb, 'x',
                       now() - interval '8 days', NULL)""",
            sid,
        )
        await conn.execute(
            """INSERT INTO pending_confirmations
                   (token, session_id, customer_id, operation_type, payload, blast_summary,
                    expires_at, consumed_at)
               VALUES ('old-consumed', $1, '1234567890', 'pause_keyword', '{}'::jsonb, 'x',
                       now() - interval '10 days', now() - interval '9 days')""",
            sid,
        )
        # Recente: expirou há menos de 7 dias -> NÃO deve ser purgada.
        await conn.execute(
            """INSERT INTO pending_confirmations
                   (token, session_id, customer_id, operation_type, payload, blast_summary,
                    expires_at, consumed_at)
               VALUES ('recent', $1, '1234567890', 'pause_keyword', '{}'::jsonb, 'x',
                       now() - interval '1 day', NULL)""",
            sid,
        )

    counts = await purge_expired(pool)

    assert counts["pending_confirmations"] == 2
    async with pool.acquire() as conn:
        remaining = await conn.fetch("SELECT token FROM pending_confirmations ORDER BY token")
    assert [r["token"] for r in remaining] == ["recent"]


@pytest.mark.integration
async def test_purge_expired_deletes_only_old_rate_counters(db):
    pool = db
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO rate_counters (developer_token_id, date, operations_used) VALUES
                   ('tok1', current_date - 91, 100),
                   ('tok1', current_date - 200, 50),
                   ('tok1', current_date - 89, 10),
                   ('tok1', current_date, 5)"""
        )

    counts = await purge_expired(pool)

    assert counts["rate_counters"] == 2
    async with pool.acquire() as conn:
        remaining = await conn.fetch("SELECT date FROM rate_counters ORDER BY date")
    assert len(remaining) == 2


@pytest.mark.integration
async def test_purge_expired_deletes_only_old_meta_rate_counters(db):
    pool = db
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO meta_rate_counters (app_id, ad_account_id, date, calls_used) VALUES
                   ('app1', 'act_1', current_date - 91, 100),
                   ('app1', 'act_1', current_date - 89, 10)"""
        )

    counts = await purge_expired(pool)

    assert counts["meta_rate_counters"] == 1
    async with pool.acquire() as conn:
        remaining = await conn.fetch("SELECT date FROM meta_rate_counters ORDER BY date")
    assert len(remaining) == 1


@pytest.mark.integration
async def test_purge_expired_never_touches_audit_log(db):
    """Decisão de produto: audit_log NUNCA é purgado (compliance)."""
    pool = db
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO audit_log (manager_id, action_type, operation, status, occurred_at)
               VALUES (NULL, 'system', 'ancient_event', 'success', now() - interval '400 days')"""
        )

    await purge_expired(pool)

    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM audit_log WHERE operation = 'ancient_event'"
        )
    assert count == 1


@pytest.mark.integration
async def test_purge_expired_returns_zero_counts_when_nothing_to_delete(db):
    pool = db
    counts = await purge_expired(pool)
    assert counts == {"pending_confirmations": 0, "rate_counters": 0, "meta_rate_counters": 0}
