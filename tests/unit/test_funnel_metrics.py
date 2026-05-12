"""Unit tests for the get_funnel_metrics MCP tool — UX-1 tracking_warning behavior."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


@pytest.fixture(autouse=True)
def _ctx():
    from src.mcp.context import McpRequestContext, clear_current, set_current

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


@pytest.mark.asyncio
async def test_funnel_includes_tracking_warning_on_1_to_1():
    """conversions_value == conversions → tracking_warning in funnel.totals."""
    from src.mcp.tools.get_funnel_metrics import get_funnel_metrics

    fake_rows = [
        {
            "impressions": 5897,
            "clicks": 382,
            "cost_micros": 1_935_680_000,
            "conversions": 93.0,
            "conversions_value": 93.0,  # 1:1 placeholder
        }
    ]

    with patch(
        "src.mcp.tools.get_funnel_metrics.run_report",
        AsyncMock(return_value=fake_rows),
    ):
        result = await get_funnel_metrics(
            {
                "customer_id": "7862230676",
                "date_range": "LAST_7_DAYS",
            }
        )

    assert "tracking_warning" in result["funnel"]["totals"]
    assert "1:1 ratio" in result["funnel"]["totals"]["tracking_warning"]


@pytest.mark.asyncio
async def test_funnel_omits_tracking_warning_on_real_tracking():
    """conversions_value > conversions → no tracking_warning in funnel.totals."""
    from src.mcp.tools.get_funnel_metrics import get_funnel_metrics

    fake_rows = [
        {
            "impressions": 1000,
            "clicks": 50,
            "cost_micros": 500_000_000,
            "conversions": 10.0,
            "conversions_value": 2500.0,
        }
    ]

    with patch(
        "src.mcp.tools.get_funnel_metrics.run_report",
        AsyncMock(return_value=fake_rows),
    ):
        result = await get_funnel_metrics(
            {
                "customer_id": "7862230676",
                "date_range": "LAST_7_DAYS",
            }
        )

    assert "tracking_warning" not in result["funnel"]["totals"]
