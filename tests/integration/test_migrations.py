"""Integration tests for the migration runner.

Uses testcontainers to spin up a real Postgres so we test the actual
behavior (idempotency, schema correctness) and not a mock.
"""

import pytest

from src.db import connection, migrate


@pytest.mark.integration
async def test_migrations_run_clean(pg_dsn: str) -> None:
    await connection.init_pool(pg_dsn, min_size=1, max_size=2)
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
async def test_migrations_are_idempotent(pg_dsn: str) -> None:
    await connection.init_pool(pg_dsn, min_size=1, max_size=2)
    try:
        await migrate.run_all()
        await migrate.run_all()  # second run must not raise
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            applied = await conn.fetch("SELECT name FROM _migrations ORDER BY name")
            # Each new migration file must be added here so this test acts as a
            # guard: if you added 003_*.sql, append it to the expected list.
            assert [r["name"] for r in applied] == [
                "001_initial_schema.sql",
                "002_managers_status.sql",
                "003_meta_schema.sql",
                "004_audit_log_provider_id.sql",
            ]
    finally:
        await connection.close_pool()
