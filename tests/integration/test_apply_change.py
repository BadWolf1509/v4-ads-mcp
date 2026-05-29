"""apply_change end-to-end with mocked Google Ads SDK."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.db.repositories import managers, mcp_sessions
from src.governance.dry_run import create_pending
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


@pytest.mark.integration
async def test_apply_change_executes_mutation(db, session_ctx):
    """Token saved as 'update_campaign_status' is consumed and a mock mutation is run."""
    from src.mcp.tools.apply_change import apply_change

    pool = db
    with patch("src.governance.dry_run.ensure_account_access", AsyncMock(return_value=None)):
        async with pool.acquire() as conn:
            token = await create_pending(
                conn,
                manager_id=session_ctx.manager_id,
                session_id=session_ctx.session_id,
                customer_id="1234567890",
                operation_type="update_campaign_status",
                payload={
                    "campaign_ids": ["111"],
                    "new_status": "PAUSED",
                    "__target_count__": 1,
                },
                blast_summary="Pausar campanha 111",
            )

    fake_client = MagicMock()
    fake_service = MagicMock()
    fake_response = MagicMock()
    fake_service.mutate = MagicMock(return_value=fake_response)
    fake_client.get_service = MagicMock(return_value=fake_service)
    fake_client.get_type = MagicMock(return_value=MagicMock(mutate_operations=[]))

    with (
        patch(
            "src.google_ads.mutations.ensure_account_access",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.google_ads.mutations.build_client_for_manager",
            AsyncMock(return_value=fake_client),
        ),
        patch(
            "src.google_ads.mutations.get_builder",
            return_value=lambda c, cid, p: [MagicMock()],
        ),
        patch(
            "src.google_ads.mutations.get_request_id",
            return_value="fake-google-request-id",
        ),
    ):
        result = await apply_change({"confirmation_token": token})

    assert result["status"] == "applied"
    assert result["operation"] == "update_campaign_status"
    assert result["provider_request_id"] == "fake-google-request-id"


@pytest.mark.integration
async def test_apply_change_returns_error_on_invalid_token(db, session_ctx):
    from src.mcp.tools.apply_change import apply_change

    result = await apply_change({"confirmation_token": "ABCD1234"})
    assert result["status"] == "error"
    assert "not found" in result["error"]
