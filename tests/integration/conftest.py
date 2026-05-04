"""Shared fixtures for integration tests that need a real Postgres container."""

import pytest
from httpx import ASGITransport, AsyncClient
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate

_SIGNING_KEY = "x" * 32
_AES_MASTER = "y" * 43


@pytest.fixture
async def pg() -> PostgresContainer:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture
async def app_with_db(pg, monkeypatch):
    dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("SESSION_SIGNING_KEY", _SIGNING_KEY)
    monkeypatch.setenv("AES_MASTER_KEY", _AES_MASTER)

    from src.app import (
        create_app,  # lazy import to avoid module-level create_app() before env is set
    )

    app = create_app(skip_db_init=True)
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        await migrate.run_all()
        yield app
    finally:
        await connection.close_pool()


@pytest.fixture
async def client(app_with_db) -> AsyncClient:
    transport = ASGITransport(app=app_with_db)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
