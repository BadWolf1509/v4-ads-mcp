"""Integration tests for the migration runner.

Uses testcontainers to spin up a real Postgres so we test the actual
behavior (idempotency, schema correctness) and not a mock.
"""

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate


@pytest.fixture
async def pg() -> PostgresContainer:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.mark.integration
async def test_migrations_run_clean(pg: PostgresContainer) -> None:
    dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    await connection.init_pool(dsn, min_size=1, max_size=2)
    try:
        await migrate.run_all()
        # Verify a known table exists.
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT to_regclass('public.audit_log') AS tbl")
            assert row["tbl"] == "audit_log"
    finally:
        await connection.close_pool()


@pytest.mark.integration
async def test_migrations_are_idempotent(pg: PostgresContainer) -> None:
    dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    await connection.init_pool(dsn, min_size=1, max_size=2)
    try:
        await migrate.run_all()
        await migrate.run_all()  # second run must not raise
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            applied = await conn.fetch("SELECT name FROM _migrations ORDER BY name")
            assert [r["name"] for r in applied] == ["001_initial_schema.sql"]
    finally:
        await connection.close_pool()
