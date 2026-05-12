"""Integration tests for keyword mutation tools."""

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
    fs.mutate = MagicMock(return_value=fr)
    fc.get_service = MagicMock(return_value=fs)
    fc.get_type = MagicMock(return_value=MagicMock(mutate_operations=[]))
    return fc


@pytest.mark.integration
async def test_update_keyword_status_single_auto_applies(db, session_ctx):
    from src.mcp.tools.update_keyword_status import update_keyword_status

    with (
        patch(
            "src.google_ads.mutations.build_client_for_manager",
            AsyncMock(return_value=_fake_client()),
        ),
        patch(
            "src.google_ads.mutations.get_builder",
            return_value=lambda c, cid, p: [MagicMock()],
        ),
        patch(
            "src.google_ads.mutations.get_request_id",
            return_value="req-kw",
        ),
    ):
        result = await update_keyword_status(
            {
                "customer_id": "1234567890",
                "keywords": [{"ad_group_id": "111", "criterion_id": "9001"}],
                "new_status": "PAUSED",
            }
        )
    assert result["status"] == "applied"


@pytest.mark.integration
async def test_update_keyword_status_bulk_dry_runs(db, session_ctx):
    from src.mcp.tools.update_keyword_status import update_keyword_status

    keywords = [{"ad_group_id": "111", "criterion_id": str(9000 + i)} for i in range(10)]
    result = await update_keyword_status(
        {
            "customer_id": "1234567890",
            "keywords": keywords,
            "new_status": "PAUSED",
        }
    )
    assert result["status"] == "dry_run"
    assert "confirmation_token" in result


@pytest.mark.integration
async def test_update_keyword_bid_small_change_auto(db, session_ctx):
    from src.mcp.tools.update_keyword_bid import update_keyword_bid

    fake_lookup = [
        {
            "ad_group_id": "111",
            "criterion_id": "9001",
            "keyword_text": "v4 ads",
            "current_cpc_bid_micros": 1_000_000,
        }
    ]
    with (
        patch(
            "src.mcp.tools.update_keyword_bid.validate_manual_cpc_strategy",
            AsyncMock(return_value=None),  # F12 pre-flight passes (Sprint 3b.8)
        ),
        patch(
            "src.mcp.tools.update_keyword_bid.run_report",
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
        patch(
            "src.google_ads.mutations.get_request_id",
            return_value="req-kw",
        ),
    ):
        result = await update_keyword_bid(
            {
                "customer_id": "1234567890",
                "bids": [
                    {
                        "ad_group_id": "111",
                        "criterion_id": "9001",
                        "new_cpc_bid_brl": 1.10,  # +10%
                    }
                ],
            }
        )
    assert result["status"] == "applied"
    assert result["changes"][0]["delta_pct"] == 10.0


@pytest.mark.integration
async def test_update_keyword_bid_large_change_dry_runs(db, session_ctx):
    from src.mcp.tools.update_keyword_bid import update_keyword_bid

    fake_lookup = [
        {
            "ad_group_id": "111",
            "criterion_id": "9001",
            "keyword_text": "v4 ads",
            "current_cpc_bid_micros": 1_000_000,
        }
    ]
    with (
        patch(
            "src.mcp.tools.update_keyword_bid.validate_manual_cpc_strategy",
            AsyncMock(return_value=None),  # F12 pre-flight passes (Sprint 3b.8)
        ),
        patch(
            "src.mcp.tools.update_keyword_bid.run_report",
            AsyncMock(return_value=fake_lookup),
        ),
    ):
        result = await update_keyword_bid(
            {
                "customer_id": "1234567890",
                "bids": [
                    {
                        "ad_group_id": "111",
                        "criterion_id": "9001",
                        "new_cpc_bid_brl": 1.30,  # +30%
                    }
                ],
            }
        )
    assert result["status"] == "dry_run"
    assert result["max_delta_pct"] == 30.0


@pytest.mark.integration
async def test_update_keyword_bid_returns_error_for_missing(db, session_ctx):
    from src.mcp.tools.update_keyword_bid import update_keyword_bid

    with (
        patch(
            "src.mcp.tools.update_keyword_bid.validate_manual_cpc_strategy",
            AsyncMock(return_value=None),  # F12 pre-flight passes (Sprint 3b.8)
        ),
        patch(
            "src.mcp.tools.update_keyword_bid.run_report",
            AsyncMock(return_value=[]),
        ),
    ):
        result = await update_keyword_bid(
            {
                "customer_id": "1234567890",
                "bids": [
                    {
                        "ad_group_id": "111",
                        "criterion_id": "9999",
                        "new_cpc_bid_brl": 1.0,
                    }
                ],
            }
        )
    assert result["status"] == "error"
