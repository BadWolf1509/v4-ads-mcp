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
                "005_meta_missed_syncs.sql",
                "006_meta_partnership_reconciliation.sql",
                "007_audit_log_dry_run.sql",
                "008_google_reconciliation.sql",
                "009_last_missed_on.sql",
            ]
    finally:
        await connection.close_pool()


@pytest.mark.integration
async def test_migration_009_statement_is_rerunnable(pg_dsn: str) -> None:
    """A migration 009 roda num Cloud Run Job ANTES do deploy: se o job falhar
    no meio (ou for reexecutado), o serviço antigo continua servindo com o
    schema parcialmente migrado. `run_all()` já é idempotente via bookkeeping
    (`_migrations`), mas isso só prova que o RUNNER pula arquivo já aplicado —
    não prova que o STATEMENT em si tolera rodar de novo contra um schema que
    já o tem. Este teste reexecuta o texto cru do arquivo 009 (fora do
    bookkeeping) numa conexão cujo schema já passou por ele, e confirma que a
    segunda execução não levanta erro. `ADD COLUMN IF NOT EXISTS` dá isso; o
    teste é para provar, não para supor.
    """
    sql = (migrate.MIGRATIONS_DIR / "009_last_missed_on.sql").read_text(encoding="utf-8")
    await connection.init_pool(pg_dsn, min_size=1, max_size=2)
    try:
        await migrate.run_all()  # aplica 001..009 uma vez, incluindo a 009 via runner
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            await conn.execute(sql)  # reexecução crua do MESMO texto — não deve levantar
            for tabela in ("google_ads_accounts", "meta_ad_accounts"):
                coluna = await conn.fetchrow(
                    "SELECT data_type, is_nullable, column_default "
                    "FROM information_schema.columns "
                    "WHERE table_name = $1 AND column_name = 'last_missed_on'",
                    tabela,
                )
                assert coluna is not None, f"{tabela}.last_missed_on sumiu após reexecução"
                assert coluna["data_type"] == "date"
                assert coluna["is_nullable"] == "YES"
                assert coluna["column_default"] is None
    finally:
        await connection.close_pool()
