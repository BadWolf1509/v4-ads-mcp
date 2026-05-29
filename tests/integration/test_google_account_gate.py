"""Integration tests for the per-account authorization gate (ensure_account_access).

Tests the real gate against a testcontainers Postgres DB:
  - Without a grant: run_report raises AccountAccessDeniedError + audits denied.
  - With a write grant: run_report passes the gate (then hits build_client_for_manager
    which we stub with a sentinel, proving the gate was cleared).

Uses the standard per-file pg/db fixture pattern (not a shared db_pool).
"""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.db.repositories import google_ads_accounts, manager_account_access, managers, mcp_sessions
from src.google_ads.access import AccountAccessDeniedError


class _SentinelError(Exception):
    """Raised by the build_client_for_manager stub to prove the gate passed."""


@pytest.fixture
async def pg() -> PostgresContainer:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture
async def db(pg: PostgresContainer):
    dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        await migrate.run_all()
        yield connection.get_pool()
    finally:
        await connection.close_pool()


@pytest.mark.integration
async def test_run_report_denied_without_grant(db) -> None:
    """run_report raises AccountAccessDeniedError + audits denied when no grant exists."""
    from src.google_ads import reports

    pool = db
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="gate@v4.com", full_name=None)
        from src.auth.sessions import generate_session_token, hash_session_token

        token = generate_session_token()
        sess = await mcp_sessions.create(
            conn, manager_id=mid, token_hash=hash_session_token(token), label="gate-test"
        )
        # Seed google_ads_accounts so the customer_id is a known account,
        # but intentionally DO NOT grant access.
        await google_ads_accounts.upsert_many(
            conn,
            [
                {
                    "customer_id": "9999999999",
                    "mcc_id": "0000000000",
                    "descriptive_name": "No-grant account",
                }
            ],
        )

    with pytest.raises(AccountAccessDeniedError) as exc_info:
        await reports.run_report(
            manager_id=mid,
            session_id=sess.id,
            customer_id="9999999999",
            query="SELECT customer.id FROM customer LIMIT 1",
            row_formatter=lambda row: {},
            operation_name="test_gate_denied",
        )

    assert "9999999999" in exc_info.value.message

    # Verify audit_log has a denied row.
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT status, customer_id, error_message FROM audit_log "
            "WHERE operation = 'test_gate_denied'"
        )
    assert len(rows) == 1
    assert rows[0]["status"] == "denied"
    assert rows[0]["customer_id"] == "9999999999"
    assert (
        "acesso" in rows[0]["error_message"].lower()
        or "sem acesso" in rows[0]["error_message"].lower()
    )


@pytest.mark.integration
async def test_run_report_allowed_with_grant(db) -> None:
    """run_report passes the gate when a write grant exists.

    After the gate, build_client_for_manager is reached — we stub it to raise
    _SentinelError so the test stays self-contained (no real Google API calls).
    The assertion is: raises _SentinelError (gate cleared), NOT AccountAccessDeniedError.
    """
    from src.google_ads import reports

    pool = db
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="gate2@v4.com", full_name=None)
        from src.auth.sessions import generate_session_token, hash_session_token

        token = generate_session_token()
        sess = await mcp_sessions.create(
            conn, manager_id=mid, token_hash=hash_session_token(token), label="gate-test-allowed"
        )
        # Seed account + grant write access.
        await google_ads_accounts.upsert_many(
            conn,
            [
                {
                    "customer_id": "8888888888",
                    "mcc_id": "0000000000",
                    "descriptive_name": "Granted account",
                }
            ],
        )
        await manager_account_access.grant(
            conn,
            manager_id=mid,
            customer_id="8888888888",
            access_level="write",
            granted_by=mid,
        )

    # Stub build_client_for_manager to raise sentinel AFTER the gate passes.
    with (
        patch(
            "src.google_ads.reports.build_client_for_manager",
            AsyncMock(side_effect=_SentinelError("stub-after-gate")),
        ),
        pytest.raises(_SentinelError, match="stub-after-gate"),
    ):
        await reports.run_report(
            manager_id=mid,
            session_id=sess.id,
            customer_id="8888888888",
            query="SELECT customer.id FROM customer LIMIT 1",
            row_formatter=lambda row: {},
            operation_name="test_gate_allowed",
        )
    # If we reach here, the gate passed (AccountAccessDeniedError was NOT raised)
    # and build_client_for_manager was called (proving the gate was cleared).
