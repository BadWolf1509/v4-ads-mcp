"""Tests for the `create-manager` admin CLI command (Task 2.3).

Creates an active manager with zero account grants — used to seed a
"smoke" manager for the authenticated MCP deploy smoke test.
"""

import argparse
from collections.abc import AsyncIterator

import pytest
from _pytest.monkeypatch import MonkeyPatch
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.db.repositories import managers
from src.scripts.admin import cmd_create_manager
from tests.integration.conftest import _clone_db

# Este teste precisa do DSN cru (não do pool já aberto): cmd_create_manager faz
# seu próprio ciclo init_pool()/close_pool() via get_settings().database_url,
# então a fixture aqui só clona um banco do template (via helper do conftest)
# e expõe o DSN — sem manter pool aberto entre chamadas.


@pytest.fixture
async def dsn(pg: PostgresContainer) -> AsyncIterator[str]:
    async with _clone_db(pg) as db_dsn:
        yield db_dsn


@pytest.fixture(autouse=True)
def _env(dsn: str, monkeypatch: MonkeyPatch) -> None:
    # cmd_create_manager reads settings.database_url via get_settings(); point it
    # at the testcontainer so the CLI's own init_pool()/close_pool() cycle works.
    monkeypatch.setenv("DATABASE_URL", dsn)


@pytest.fixture
async def migrated(dsn: str) -> AsyncIterator[None]:
    """Run migrations once, then leave the pool closed for the CLI to own."""
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        await migrate.run_all()
        yield
    finally:
        await connection.close_pool()


def _args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {"email": "smoke@v4company.com", "name": None}
    return argparse.Namespace(**{**defaults, **overrides})


@pytest.mark.integration
async def test_create_manager_active_no_grants(migrated: None, dsn: str) -> None:
    """First call creates an active manager with no account grants."""
    rc = await cmd_create_manager(_args(name="Smoke Test"))
    assert rc == 0

    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            m = await managers.get_by_email(conn, "smoke@v4company.com")
            assert m is not None
            assert m.status == "active"
            assert m.is_active is True
            assert m.role == "gestor"
            assert m.full_name == "Smoke Test"

            grants = await conn.fetchval(
                "SELECT count(*) FROM manager_account_access WHERE manager_id = $1", m.id
            )
            assert grants == 0
    finally:
        await connection.close_pool()


@pytest.mark.integration
async def test_create_manager_idempotent(migrated: None, dsn: str) -> None:
    """Second call for the same email does not duplicate the row."""
    rc1 = await cmd_create_manager(_args())
    assert rc1 == 0

    rc2 = await cmd_create_manager(_args())
    assert rc2 == 0

    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT count(*) FROM managers WHERE email = $1", "smoke@v4company.com"
            )
            assert count == 1
    finally:
        await connection.close_pool()
