"""Unit tests for the get_account_overview MCP tool — UX-1 tracking_warning behavior."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


@pytest.fixture(autouse=True)
def _ctx():
    from datetime import date

    from src.mcp.context import McpRequestContext, clear_current, set_current

    async def _hoje(customer_id: str, *, now=None):
        return date(2026, 5, 15)

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    # F141: a tool resolve `hoje` no fuso da conta lendo o DB; aqui nao ha pool.
    with patch("src.mcp.tools.get_account_overview.resolve_account_today", _hoje):
        yield
    clear_current()


@pytest.mark.asyncio
async def test_overview_includes_tracking_warning_on_1_to_1():
    """conversions_value == conversions in current period → tracking_warning field present."""
    from src.mcp.tools.get_account_overview import get_account_overview

    # Mock run_report to return placeholder-tracking rows
    fake_rows_curr = [
        {
            "impressions": 5897,
            "clicks": 382,
            "cost_micros": 1_935_680_000,
            "conversions": 93.0,
            "conversions_value": 93.0,  # 1:1 placeholder
        }
    ]
    fake_rows_prev = [
        {
            "impressions": 10756,
            "clicks": 697,
            "cost_micros": 1_435_570_000,
            "conversions": 727.49,
            "conversions_value": 727.49,  # also 1:1
        }
    ]

    with patch(
        "src.mcp.tools.get_account_overview.run_report",
        AsyncMock(side_effect=[fake_rows_curr, fake_rows_prev]),
    ):
        result = await get_account_overview(
            {
                "customer_id": "7862230676",
                "date_range": "LAST_7_DAYS",
            }
        )

    assert "tracking_warning" in result["current"]
    assert "1:1 ratio" in result["current"]["tracking_warning"]
    assert "tracking_warning" in result["previous"]


@pytest.mark.asyncio
async def test_overview_omits_tracking_warning_on_real_tracking():
    """conversions_value > conversions → no tracking_warning field."""
    from src.mcp.tools.get_account_overview import get_account_overview

    fake_rows_curr = [
        {
            "impressions": 1000,
            "clicks": 50,
            "cost_micros": 500_000_000,
            "conversions": 10.0,
            "conversions_value": 2500.0,  # real revenue tracking
        }
    ]
    fake_rows_prev = [
        {
            "impressions": 800,
            "clicks": 40,
            "cost_micros": 400_000_000,
            "conversions": 8.0,
            "conversions_value": 2000.0,
        }
    ]

    with patch(
        "src.mcp.tools.get_account_overview.run_report",
        AsyncMock(side_effect=[fake_rows_curr, fake_rows_prev]),
    ):
        result = await get_account_overview(
            {
                "customer_id": "7862230676",
                "date_range": "LAST_7_DAYS",
            }
        )

    assert "tracking_warning" not in result["current"]
    assert "tracking_warning" not in result["previous"]
