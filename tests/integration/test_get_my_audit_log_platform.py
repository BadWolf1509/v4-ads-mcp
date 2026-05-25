"""Regression test A5: get_my_audit_log returns platform field per row."""

from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.db.repositories import audit_log, managers


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
async def db_with_rows(db):
    """Insert 1 google + 1 meta audit_log row pra mesmo manager."""
    mid = uuid4()
    pool = db
    async with pool.acquire() as conn:
        await managers.create(conn, manager_id=mid, email="t@v4company.com", full_name="Tester")
        # Google row (default platform)
        await audit_log.record(
            conn,
            manager_id=mid,
            session_id=None,
            customer_id=None,
            action_type="read",
            operation="list_my_accounts",
            status="success",
            # platform=google by default
        )
        # Meta row (explicit platform)
        await audit_log.record(
            conn,
            manager_id=mid,
            session_id=None,
            customer_id="act_123",
            action_type="read",
            operation="meta_list_my_ad_accounts",
            status="success",
            platform="meta",
        )
    return mid


@pytest.mark.integration
async def test_list_for_manager_returns_platform_field(db_with_rows, db):
    """list_for_manager rows MUST contain 'platform' field."""
    pool = db
    async with pool.acquire() as conn:
        rows = await audit_log.list_for_manager(conn, manager_id=db_with_rows, days=7, limit=10)
    assert len(rows) == 2
    assert all("platform" in r for r in rows), f"missing platform field in rows: {rows}"
    platforms = {r["platform"] for r in rows}
    assert platforms == {"google", "meta"}, f"unexpected platforms: {platforms}"
