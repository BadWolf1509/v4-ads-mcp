"""Integration tests for mcp_sessions.get_by_id (manager-scoped lookup)."""

from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.db.repositories import mcp_sessions


@pytest.fixture
async def pg() -> PostgresContainer:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture
async def db(pg: PostgresContainer):
    """Initialize pool + run migrations once; yield pool, then tear down."""
    dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        await migrate.run_all()
        yield connection.get_pool()
    finally:
        await connection.close_pool()


@pytest.mark.integration
async def test_get_by_id_returns_session_when_owned(db) -> None:
    mid = uuid4()
    sid = uuid4()
    async with db.acquire() as conn:
        await conn.execute(
            "INSERT INTO managers (id, email, status, role) VALUES ($1, 'a@v4company.com', 'active', 'gestor')",
            mid,
        )
        await conn.execute(
            "INSERT INTO mcp_sessions (id, manager_id, label, token_hash) VALUES ($1, $2, 'Test', 'h')",
            sid,
            mid,
        )
        result = await mcp_sessions.get_by_id(conn, session_id=sid, manager_id=mid)
    assert result is not None
    assert result["label"] == "Test"


@pytest.mark.integration
async def test_get_by_id_returns_none_when_not_owned(db) -> None:
    mid = uuid4()
    other = uuid4()
    sid = uuid4()
    async with db.acquire() as conn:
        await conn.execute(
            """INSERT INTO managers (id, email, status, role) VALUES
               ($1, 'a@v4company.com', 'active', 'gestor'),
               ($2, 'b@v4company.com', 'active', 'gestor')""",
            mid,
            other,
        )
        await conn.execute(
            "INSERT INTO mcp_sessions (id, manager_id, label, token_hash) VALUES ($1, $2, 'OtherTest', 'h')",
            sid,
            other,
        )
        result = await mcp_sessions.get_by_id(conn, session_id=sid, manager_id=mid)
    assert result is None
