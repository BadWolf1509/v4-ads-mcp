"""Integration tests for the MCP Bearer → context resolution."""

from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.auth.sessions import generate_session_token, hash_session_token
from src.db import connection, migrate
from src.db.repositories import managers, mcp_sessions
from src.mcp.session import (
    UnauthorizedError,
    resolve_session_to_context,
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


@pytest.mark.integration
async def test_valid_bearer_resolves_context(db) -> None:
    pool = db
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="r@v4.com", full_name=None)
        token = generate_session_token()
        sess = await mcp_sessions.create(
            conn,
            manager_id=mid,
            token_hash=hash_session_token(token),
            label="t",
        )

    ctx = await resolve_session_to_context(f"Bearer {token}")
    assert ctx.manager_id == mid
    assert ctx.session_id == sess.id


@pytest.mark.integration
async def test_missing_header_raises_unauthorized(db) -> None:
    with pytest.raises(UnauthorizedError, match="Missing"):
        await resolve_session_to_context(None)


@pytest.mark.integration
async def test_unknown_token_raises_unauthorized(db) -> None:
    with pytest.raises(UnauthorizedError, match="not found"):
        await resolve_session_to_context("Bearer mcp_definitely_not_a_real_token")


@pytest.mark.integration
async def test_revoked_session_raises_unauthorized(db) -> None:
    pool = db
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="rv@v4.com", full_name=None)
        token = generate_session_token()
        sess = await mcp_sessions.create(
            conn,
            manager_id=mid,
            token_hash=hash_session_token(token),
            label="t",
        )
        await mcp_sessions.revoke(conn, sess.id)

    with pytest.raises(UnauthorizedError):
        await resolve_session_to_context(f"Bearer {token}")


@pytest.mark.integration
async def test_resolution_touches_last_used(db) -> None:
    pool = db
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="tu@v4.com", full_name=None)
        token = generate_session_token()
        sess = await mcp_sessions.create(
            conn,
            manager_id=mid,
            token_hash=hash_session_token(token),
            label="t",
        )
        assert sess.last_used_at is None

    await resolve_session_to_context(f"Bearer {token}")

    async with pool.acquire() as conn:
        refreshed_list = await mcp_sessions.list_for_manager(conn, mid)
        assert refreshed_list[0].last_used_at is not None
