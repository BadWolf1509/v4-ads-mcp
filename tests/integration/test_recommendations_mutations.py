"""Integration tests for recommendation mutation tools."""

from unittest.mock import AsyncMock, MagicMock, patch
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


def _fake_client_with_response(request_id: str = "req-rec"):
    fc = MagicMock()
    fr = MagicMock()
    fr.request_id = request_id
    fs = MagicMock()
    fs.apply_recommendation = MagicMock(return_value=fr)
    fs.dismiss_recommendation = MagicMock(return_value=fr)
    fc.get_service = MagicMock(return_value=fs)
    fc.get_type = MagicMock(return_value=MagicMock())
    return fc


@pytest.mark.integration
async def test_apply_recommendation_auto_applies(db, session_ctx):
    from src.mcp.tools.apply_recommendation import apply_recommendation

    with patch(
        "src.google_ads.mutations.build_client_for_manager",
        AsyncMock(return_value=_fake_client_with_response("req-apply")),
    ):
        result = await apply_recommendation(
            {
                "customer_id": "1234567890",
                "recommendation_resource_name": "customers/1234567890/recommendations/abc",
            }
        )

    assert result["status"] == "applied"
    assert result["operation"] == "apply_recommendation"
    assert result["google_request_id"] == "req-apply"


@pytest.mark.integration
async def test_dismiss_recommendation_auto_applies(db, session_ctx):
    from src.mcp.tools.dismiss_recommendation import dismiss_recommendation

    with patch(
        "src.google_ads.mutations.build_client_for_manager",
        AsyncMock(return_value=_fake_client_with_response("req-dismiss")),
    ):
        result = await dismiss_recommendation(
            {
                "customer_id": "1234567890",
                "recommendation_resource_name": "customers/1234567890/recommendations/xyz",
            }
        )

    assert result["status"] == "applied"
    assert result["operation"] == "dismiss_recommendation"
    assert result["google_request_id"] == "req-dismiss"
