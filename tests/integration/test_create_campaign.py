"""Integration: create_campaign end-to-end with mocked SDK + real DB (testcontainers)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.db.repositories import google_ads_accounts, manager_account_access, managers, mcp_sessions
from src.mcp.context import McpRequestContext, clear_current, set_current

pytestmark = pytest.mark.integration


@pytest.fixture
async def session_ctx(db):
    """Create real manager + session rows so create_pending FK doesn't violate.

    Sprint 3b.25 fix for chronic CI red: pending_confirmations.session_id has
    FK to mcp_sessions(id) since migration 001, but Sprint 3b.24's original
    test used set_current with session_id=uuid4() random — violating the FK
    in CI (caught only on testcontainers run, not local fast pre-push gate).
    """
    pool = db
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="t@v4.com", full_name=None)
        from src.auth.sessions import generate_session_token, hash_session_token

        token = generate_session_token()
        sess = await mcp_sessions.create(
            conn, manager_id=mid, token_hash=hash_session_token(token), label="t"
        )
    # Seed google_ads_accounts + grant write access so ensure_account_access passes.
    async with pool.acquire() as conn:
        await google_ads_accounts.upsert_many(
            conn,
            [{"customer_id": "1234567890", "mcc_id": "0000000000", "descriptive_name": "Test"}],
        )
        await manager_account_access.grant(
            conn, manager_id=mid, customer_id="1234567890", access_level="write", granted_by=mid
        )
    ctx = McpRequestContext(manager_id=mid, session_id=sess.id)
    set_current(ctx)
    yield ctx
    clear_current()


@pytest.mark.asyncio
async def test_create_campaign_dry_run_creates_pending_token(db, session_ctx):
    """Tool returns dry_run + token; audit_log row only on apply, not dry_run."""
    from src.mcp.tools.create_campaign import create_campaign

    with patch(
        "src.mcp.tools.create_campaign.validate_geo_target_constants_br_only",
        AsyncMock(return_value=None),
    ):
        result = await create_campaign(
            {
                "customer_id": "1234567890",
                "name": "[3b.24 integration] Test",
                "bidding_strategy": {"type": "MAXIMIZE_CONVERSIONS"},
                "daily_budget_brl": 10.0,
                "geo_targets": ["geoTargetConstants/2076"],
            }
        )

    assert result["status"] == "dry_run"
    assert "confirmation_token" in result
    assert len(result["confirmation_token"]) == 8
    assert result["preview"]["bidding_strategy_type"] == "MAXIMIZE_CONVERSIONS"
    assert result["preview"]["geo_count"] == 1
    assert result["preview"]["has_schedule"] is False
    assert "SEARCH" in result["blast_summary"]
    assert "PAUSED" in result["blast_summary"]


@pytest.mark.asyncio
async def test_create_campaign_pre_flight_geo_rejection(db, session_ctx):
    """Non-BR geo path → tool returns error before creating dry_run token."""
    from src.mcp.tools.create_campaign import create_campaign

    with patch(
        "src.mcp.tools.create_campaign.validate_geo_target_constants_br_only",
        AsyncMock(return_value="Geo target tem country_code 'CA', esperado 'BR'."),
    ):
        result = await create_campaign(
            {
                "customer_id": "1234567890",
                "name": "[3b.24] Bad geo test",
                "bidding_strategy": {"type": "MAXIMIZE_CONVERSIONS"},
                "daily_budget_brl": 10.0,
                "geo_targets": ["geoTargetConstants/2124"],  # Canada
            }
        )

    assert result["status"] == "error"
    assert "BR" in result["error"]
    assert "confirmation_token" not in result
