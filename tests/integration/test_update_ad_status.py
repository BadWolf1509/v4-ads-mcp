"""Integration tests for update_ad_status (real Postgres, mocked SDK)."""

from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.db.repositories import managers, mcp_sessions
from src.mcp.context import McpRequestContext, clear_current, set_current


@pytest.fixture
async def pg() -> PostgresContainer:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture
async def db(pg):
    dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        await migrate.run_all()
        yield connection.get_pool()
    finally:
        await connection.close_pool()


@pytest.fixture
async def session_ctx(db):
    pool = db
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="t@v4.com", full_name=None)
        from src.auth.sessions import generate_session_token, hash_session_token

        token = generate_session_token()
        sess = await mcp_sessions.create(
            conn, manager_id=mid, token_hash=hash_session_token(token), label="t"
        )
    ctx = McpRequestContext(manager_id=mid, session_id=sess.id)
    set_current(ctx)
    yield ctx
    clear_current()


@pytest.mark.integration
async def test_update_ad_status_remove_creates_token_even_one_ad(db, session_ctx):
    """1 ad + REMOVED → CONFIRM path (despite count=1) → pending_confirmations row created."""
    from src.mcp.tools.update_ad_status import update_ad_status

    result = await update_ad_status(
        {
            "customer_id": "1234567890",
            "ads": [{"ad_group_id": "111", "ad_id": "222"}],
            "new_status": "REMOVED",
        }
    )

    assert result["status"] == "dry_run"
    assert "confirmation_token" in result
    token = result["confirmation_token"]

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT operation_type, customer_id, payload, consumed_at "
            "FROM pending_confirmations WHERE token = $1",
            token,
        )
    assert row is not None
    assert row["operation_type"] == "update_ad_status"
    assert row["customer_id"] == "1234567890"
    assert row["consumed_at"] is None
