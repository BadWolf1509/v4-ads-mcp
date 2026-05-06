"""Integration tests for the 3 campaign mutation tools."""

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


@pytest.mark.integration
async def test_update_campaign_status_single_auto_applies(db, session_ctx):
    """1 campaign -> auto-apply path."""
    from src.mcp.tools.update_campaign_status import update_campaign_status

    fake_client = MagicMock()
    fake_service = MagicMock()
    fake_response = MagicMock()
    fake_response._underlay_call.trailing_metadata.return_value = [("request-id", "req-123")]
    fake_service.mutate = MagicMock(return_value=fake_response)
    fake_client.get_service = MagicMock(return_value=fake_service)
    fake_client.get_type = MagicMock(return_value=MagicMock(mutate_operations=[]))

    with (
        patch(
            "src.google_ads.mutations.build_client_for_manager",
            AsyncMock(return_value=fake_client),
        ),
        patch(
            "src.google_ads.mutations.get_builder",
            return_value=lambda c, cid, p: [MagicMock()],
        ),
    ):
        result = await update_campaign_status(
            {
                "customer_id": "1234567890",
                "campaign_ids": ["111"],
                "new_status": "PAUSED",
            }
        )

    assert result["status"] == "applied"
    assert result["google_request_id"] == "req-123"
    assert result["applied_count"] == 1


@pytest.mark.integration
async def test_update_campaign_status_bulk_dry_runs(db, session_ctx):
    """6 campaigns -> dry-run path with confirmation_token."""
    from src.mcp.tools.update_campaign_status import update_campaign_status

    result = await update_campaign_status(
        {
            "customer_id": "1234567890",
            "campaign_ids": [str(i) for i in range(100, 106)],  # 6 campaigns
            "new_status": "PAUSED",
        }
    )

    assert result["status"] == "dry_run"
    assert "confirmation_token" in result
    assert len(result["confirmation_token"]) == 8


@pytest.mark.integration
async def test_update_campaign_budget_dry_runs_with_delta(db, session_ctx):
    """Budget mutations always dry-run; tool resolves current budget via GAQL lookup."""
    from src.mcp.tools.update_campaign_budget import update_campaign_budget

    fake_lookup_rows = [
        {
            "campaign_budget_resource_name": "customers/1234567890/campaignBudgets/9999",
            "current_amount_micros": 100_000_000,  # R$ 100
            "campaign_name": "Test Campaign",
        }
    ]
    with patch(
        "src.mcp.tools.update_campaign_budget.run_report",
        AsyncMock(return_value=fake_lookup_rows),
    ):
        result = await update_campaign_budget(
            {
                "customer_id": "1234567890",
                "campaign_id": "555",
                "new_daily_budget_brl": 150.0,  # R$ 100 -> R$ 150 = +50%
            }
        )

    assert result["status"] == "dry_run"
    assert result["current_amount_brl"] == 100.0
    assert result["new_amount_brl"] == 150.0
    assert result["delta_pct"] == 50.0
    assert "confirmation_token" in result


@pytest.mark.integration
async def test_update_campaign_budget_returns_error_when_campaign_not_found(db, session_ctx):
    from src.mcp.tools.update_campaign_budget import update_campaign_budget

    with patch(
        "src.mcp.tools.update_campaign_budget.run_report",
        AsyncMock(return_value=[]),
    ):
        result = await update_campaign_budget(
            {
                "customer_id": "1234567890",
                "campaign_id": "999",
                "new_daily_budget_brl": 100.0,
            }
        )
    assert result["status"] == "error"
    assert "nao encontrada" in result["error"]


@pytest.mark.integration
async def test_update_campaign_bidding_target_cpa_dry_runs(db, session_ctx):
    from src.mcp.tools.update_campaign_bidding import update_campaign_bidding

    result = await update_campaign_bidding(
        {
            "customer_id": "1234567890",
            "campaign_id": "555",
            "strategy": "TARGET_CPA",
            "target_cpa_brl": 25.0,
        }
    )

    assert result["status"] == "dry_run"
    assert "confirmation_token" in result
    assert "TARGET_CPA" in result["blast_summary"]


@pytest.mark.integration
async def test_update_campaign_bidding_target_cpa_missing_value_returns_error(db, session_ctx):
    from src.mcp.tools.update_campaign_bidding import update_campaign_bidding

    result = await update_campaign_bidding(
        {
            "customer_id": "1234567890",
            "campaign_id": "555",
            "strategy": "TARGET_CPA",
            # missing target_cpa_brl
        }
    )
    assert result["status"] == "error"
    assert "target_cpa_brl" in result["error"]
