"""Integration tests for update_conversion_action tool (Sprint 3b.27).

Mock helper at TOOL's namespace (NOT _common's) — convention pós-3b.5/3b.8
(F-class "Pre-flight test mocks"). Patching at _common.py would slip the
local pre-push gate (which doesn't run DB integration) and surface only
in CI.
"""

from unittest.mock import AsyncMock, patch
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


@pytest.mark.integration
async def test_layer2_rejects_no_mutable_field(db, session_ctx):
    """Layer 2 rejects an item with only conversion_action_id (no mutable fields)."""
    from src.mcp.tools.update_conversion_action import update_conversion_action

    args = {
        "customer_id": "1163862076",
        "updates": [{"conversion_action_id": "123"}],
    }
    result = await update_conversion_action(args)
    assert result["status"] == "error"
    assert "sem nenhum field mutável" in result["error"]


@pytest.mark.integration
async def test_preflight_missing_id_returns_error(db, session_ctx):
    """Mock preflight at TOOL's namespace (convention pós-3b.5/3b.8)."""
    from src.mcp.tools.update_conversion_action import update_conversion_action

    args = {
        "customer_id": "1163862076",
        "updates": [{"conversion_action_id": "999", "name": "x"}],
    }
    with patch(
        "src.mcp.tools.update_conversion_action.validate_conversion_actions_exist",
        AsyncMock(return_value={"error": "999 não existe", "missing_ids": ["999"]}),
    ):
        result = await update_conversion_action(args)
    assert result["status"] == "error"
    assert result["missing_ids"] == ["999"]


@pytest.mark.integration
async def test_single_rename_auto_applies(db, session_ctx):
    """Single rename only is AUTO — calls run_mutation directly."""
    from src.mcp.tools.update_conversion_action import update_conversion_action

    args = {
        "customer_id": "1163862076",
        "updates": [{"conversion_action_id": "123", "name": "Renamed"}],
    }
    with (
        patch(
            "src.mcp.tools.update_conversion_action.validate_conversion_actions_exist",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.mcp.tools.update_conversion_action.run_mutation",
            AsyncMock(return_value={"applied_count": 1, "google_request_id": "req-abc"}),
        ),
    ):
        result = await update_conversion_action(args)
    assert result["status"] == "applied"
    assert result["applied_count"] == 1
    assert result["google_request_id"] == "req-abc"
    assert result["changes"][0]["fields_updated"] == ["name"]


@pytest.mark.integration
async def test_disable_primary_for_goal_returns_dry_run(db, session_ctx):
    """Setting primary_for_goal=False is CONFIRM — returns confirmation_token."""
    from src.mcp.tools.update_conversion_action import update_conversion_action

    args = {
        "customer_id": "1163862076",
        "updates": [{"conversion_action_id": "123", "primary_for_goal": False}],
    }
    with patch(
        "src.mcp.tools.update_conversion_action.validate_conversion_actions_exist",
        AsyncMock(return_value=None),
    ):
        result = await update_conversion_action(args)
    assert result["status"] == "dry_run"
    assert "confirmation_token" in result
    assert result["changes"][0]["fields_updated"] == ["primary_for_goal"]
