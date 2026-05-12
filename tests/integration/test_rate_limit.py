"""Rate limit logic tests against testcontainers Postgres."""

from datetime import UTC, datetime, timedelta

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.governance.rate_limit import (
    DAILY_QUOTA_BASIC,
    QuotaExhausted,
    before_call,
    get_today_usage,
    record_actual,
)


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


_TOKEN_ID = "dev-token-hash-fixture"


@pytest.mark.integration
async def test_first_call_starts_counter_at_estimate(db) -> None:
    pool = db
    async with pool.acquire() as conn:
        await before_call(conn, _TOKEN_ID, estimated_ops=10)
        used, limit, pct = await get_today_usage(conn, _TOKEN_ID)
    assert used == 10
    assert limit == DAILY_QUOTA_BASIC
    assert pct == pytest.approx(10 / DAILY_QUOTA_BASIC, rel=0.01)


@pytest.mark.integration
async def test_record_actual_reconciles_estimate(db) -> None:
    pool = db
    async with pool.acquire() as conn:
        await before_call(conn, _TOKEN_ID, estimated_ops=10)
        # Google said only 7 ops actually used.
        await record_actual(conn, _TOKEN_ID, actual_ops=7, estimated_ops=10)
        used, _, _ = await get_today_usage(conn, _TOKEN_ID)
    assert used == 7  # reconciled down


@pytest.mark.integration
async def test_blocks_at_100_percent(db) -> None:
    pool = db
    async with pool.acquire() as conn:
        # Bump counter to limit - 5
        await before_call(conn, _TOKEN_ID, estimated_ops=DAILY_QUOTA_BASIC - 5)
        # Next call estimating 10 would push to limit + 5 → must block
        with pytest.raises(QuotaExhausted, match="quota di"):
            await before_call(conn, _TOKEN_ID, estimated_ops=10)


@pytest.mark.integration
async def test_warns_at_80_percent_only_once(db) -> None:
    """80% warning fires once per day per token (last_alert_pct prevents repeat)."""
    pool = db
    async with pool.acquire() as conn:
        # Push to ~75%
        await before_call(conn, _TOKEN_ID, estimated_ops=int(DAILY_QUOTA_BASIC * 0.75))
        # No warning yet
        # Push past 80%
        await before_call(conn, _TOKEN_ID, estimated_ops=int(DAILY_QUOTA_BASIC * 0.10))
        # Push again — should NOT re-warn
        await before_call(conn, _TOKEN_ID, estimated_ops=100)
        # Confirm last_alert_pct is 80
        row = await conn.fetchrow(
            "SELECT last_alert_pct FROM rate_counters WHERE developer_token_id = $1",
            _TOKEN_ID,
        )
    assert row["last_alert_pct"] == 80


@pytest.mark.integration
async def test_separate_days_have_independent_counters(db) -> None:
    """Yesterday's count doesn't bleed into today."""
    pool = db
    async with pool.acquire() as conn:
        # Insert yesterday's counter manually at 95% used
        yesterday = (datetime.now(UTC) - timedelta(days=1)).date()
        await conn.execute(
            """
            INSERT INTO rate_counters (developer_token_id, date, operations_used, last_alert_pct)
            VALUES ($1, $2, $3, $4)
            """,
            _TOKEN_ID,
            yesterday,
            int(DAILY_QUOTA_BASIC * 0.95),
            80,
        )
        # Today's call should succeed with fresh counter
        await before_call(conn, _TOKEN_ID, estimated_ops=100)
        used, _, _ = await get_today_usage(conn, _TOKEN_ID)
    assert used == 100  # only today's count


@pytest.mark.integration
async def test_concurrent_increments_serialize_via_for_update(db) -> None:
    """Two concurrent before_call calls must not double-count."""
    import asyncio

    pool = db

    async def call_once():
        async with pool.acquire() as conn:
            await before_call(conn, _TOKEN_ID, estimated_ops=100)

    await asyncio.gather(*[call_once() for _ in range(5)])

    async with pool.acquire() as conn:
        used, _, _ = await get_today_usage(conn, _TOKEN_ID)
    assert used == 500  # exactly 5 * 100, no over/under count
