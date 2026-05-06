"""Integration tests for ad_group mutation tools."""

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


def _fake_client():
    fc = MagicMock()
    fs = MagicMock()
    fr = MagicMock()
    fr._underlay_call.trailing_metadata.return_value = [("request-id", "req-ag")]
    fs.mutate = MagicMock(return_value=fr)
    fc.get_service = MagicMock(return_value=fs)
    fc.get_type = MagicMock(return_value=MagicMock(mutate_operations=[]))
    return fc


@pytest.mark.integration
async def test_update_ad_group_status_single_auto_applies(db, session_ctx):
    from src.mcp.tools.update_ad_group_status import update_ad_group_status

    with (
        patch(
            "src.google_ads.mutations.build_client_for_manager",
            AsyncMock(return_value=_fake_client()),
        ),
        patch(
            "src.google_ads.mutations.get_builder",
            return_value=lambda c, cid, p: [MagicMock()],
        ),
    ):
        result = await update_ad_group_status(
            {
                "customer_id": "1234567890",
                "ad_group_ids": ["222"],
                "new_status": "PAUSED",
            }
        )
    assert result["status"] == "applied"


@pytest.mark.integration
async def test_update_ad_group_status_bulk_dry_runs(db, session_ctx):
    from src.mcp.tools.update_ad_group_status import update_ad_group_status

    result = await update_ad_group_status(
        {
            "customer_id": "1234567890",
            "ad_group_ids": [str(i) for i in range(200, 210)],  # 10 ad groups
            "new_status": "PAUSED",
        }
    )
    assert result["status"] == "dry_run"
    assert "confirmation_token" in result


@pytest.mark.integration
async def test_update_ad_group_bid_small_change_auto(db, session_ctx):
    """1 ad group, +10% bid change -> auto-apply."""
    from src.mcp.tools.update_ad_group_bid import update_ad_group_bid

    fake_lookup = [
        {
            "ad_group_id": "222",
            "ad_group_name": "Brand",
            "current_cpc_bid_micros": 1_000_000,  # R$ 1.00
        }
    ]
    with (
        patch(
            "src.mcp.tools.update_ad_group_bid.run_report",
            AsyncMock(return_value=fake_lookup),
        ),
        patch(
            "src.google_ads.mutations.build_client_for_manager",
            AsyncMock(return_value=_fake_client()),
        ),
        patch(
            "src.google_ads.mutations.get_builder",
            return_value=lambda c, cid, p: [MagicMock()],
        ),
    ):
        result = await update_ad_group_bid(
            {
                "customer_id": "1234567890",
                "bids": [{"ad_group_id": "222", "new_cpc_bid_brl": 1.10}],  # +10%
            }
        )
    assert result["status"] == "applied"
    assert result["changes"][0]["delta_pct"] == 10.0


@pytest.mark.integration
async def test_update_ad_group_bid_large_change_dry_runs(db, session_ctx):
    """1 ad group, +25% bid change -> dry-run (>20% threshold)."""
    from src.mcp.tools.update_ad_group_bid import update_ad_group_bid

    fake_lookup = [
        {
            "ad_group_id": "222",
            "ad_group_name": "Brand",
            "current_cpc_bid_micros": 1_000_000,
        }
    ]
    with patch(
        "src.mcp.tools.update_ad_group_bid.run_report",
        AsyncMock(return_value=fake_lookup),
    ):
        result = await update_ad_group_bid(
            {
                "customer_id": "1234567890",
                "bids": [{"ad_group_id": "222", "new_cpc_bid_brl": 1.30}],  # +30%
            }
        )
    assert result["status"] == "dry_run"
    assert result["max_delta_pct"] == 30.0
    assert "confirmation_token" in result


@pytest.mark.integration
async def test_update_ad_group_bid_returns_error_for_missing(db, session_ctx):
    from src.mcp.tools.update_ad_group_bid import update_ad_group_bid

    with patch(
        "src.mcp.tools.update_ad_group_bid.run_report",
        AsyncMock(return_value=[]),  # ad group not found
    ):
        result = await update_ad_group_bid(
            {
                "customer_id": "1234567890",
                "bids": [{"ad_group_id": "999", "new_cpc_bid_brl": 1.0}],
            }
        )
    assert result["status"] == "error"
    assert "999" in result["error"]
