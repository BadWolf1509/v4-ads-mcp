"""Integration: create_campaign end-to-end with mocked SDK + real DB (testcontainers)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.mcp.context import McpRequestContext, clear_current, set_current

pytestmark = pytest.mark.integration


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


@pytest.mark.asyncio
async def test_create_campaign_dry_run_creates_pending_token(db):
    """Tool returns dry_run + token; audit_log row only on apply, not dry_run."""
    from src.mcp.tools.create_campaign import create_campaign

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    try:
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
    finally:
        clear_current()


@pytest.mark.asyncio
async def test_create_campaign_pre_flight_geo_rejection(db):
    """Non-BR geo path → tool returns error before creating dry_run token."""
    from src.mcp.tools.create_campaign import create_campaign

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    try:
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
    finally:
        clear_current()
