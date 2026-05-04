"""Integration tests for the 5 performance tools — mock run_report, verify shape."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current


@pytest.fixture
def bound_context():
    ctx = McpRequestContext(manager_id=uuid4(), session_id=uuid4())
    set_current(ctx)
    yield ctx
    clear_current()


@pytest.mark.asyncio
async def test_campaign_performance_returns_rows(bound_context):
    from src.mcp.tools.get_campaign_performance import get_campaign_performance

    fake_rows = [
        {
            "campaign_id": "111",
            "campaign_name": "Brand",
            "status": "ENABLED",
            "type": "SEARCH",
            "impressions": 10000,
            "clicks": 500,
            "cost_brl": 250.0,
            "conversions": 25.0,
            "conversions_value_brl": 5000.0,
            "ctr": 0.05,
            "cpc_brl": 0.50,
        },
    ]
    with patch(
        "src.mcp.tools.get_campaign_performance.run_report",
        AsyncMock(return_value=fake_rows),
    ):
        result = await get_campaign_performance(
            {
                "customer_id": "1234567890",
                "date_range": "LAST_7_DAYS",
            }
        )

    assert result["customer_id"] == "1234567890"
    assert len(result["rows"]) == 1
    assert result["rows"][0]["campaign_id"] == "111"


@pytest.mark.asyncio
async def test_ad_group_performance_returns_rows(bound_context):
    from src.mcp.tools.get_ad_group_performance import get_ad_group_performance

    fake_rows = [
        {
            "ad_group_id": "222",
            "ad_group_name": "Brand - Exact",
            "status": "ENABLED",
            "campaign_id": "111",
            "campaign_name": "Brand",
            "impressions": 5000,
            "clicks": 250,
            "cost_brl": 100.0,
            "conversions": 10.0,
            "conversions_value_brl": 2000.0,
            "ctr": 0.05,
            "cpc_brl": 0.40,
        }
    ]
    with patch(
        "src.mcp.tools.get_ad_group_performance.run_report",
        AsyncMock(return_value=fake_rows),
    ):
        result = await get_ad_group_performance({"customer_id": "1234567890"})

    assert len(result["rows"]) == 1
    assert result["rows"][0]["ad_group_id"] == "222"


@pytest.mark.asyncio
async def test_device_performance_returns_rows(bound_context):
    from src.mcp.tools.get_device_performance import get_device_performance

    fake_rows = [
        {
            "device": "MOBILE",
            "impressions": 5000,
            "clicks": 200,
            "cost_brl": 100.0,
            "conversions": 10.0,
            "conversions_value_brl": 1000.0,
            "ctr": 0.04,
            "cpc_brl": 0.50,
        },
        {
            "device": "DESKTOP",
            "impressions": 3000,
            "clicks": 150,
            "cost_brl": 80.0,
            "conversions": 8.0,
            "conversions_value_brl": 800.0,
            "ctr": 0.05,
            "cpc_brl": 0.53,
        },
    ]
    with patch(
        "src.mcp.tools.get_device_performance.run_report",
        AsyncMock(return_value=fake_rows),
    ):
        result = await get_device_performance({"customer_id": "1234567890"})

    assert len(result["rows"]) == 2
    devices = {r["device"] for r in result["rows"]}
    assert devices == {"MOBILE", "DESKTOP"}


@pytest.mark.asyncio
async def test_geo_performance_returns_rows(bound_context):
    from src.mcp.tools.get_geo_performance import get_geo_performance

    fake_rows = [
        {
            "country_criterion_id": "2076",  # Brazil
            "impressions": 10000,
            "clicks": 500,
            "cost_brl": 250.0,
            "conversions": 25.0,
            "conversions_value_brl": 5000.0,
            "ctr": 0.05,
            "cpc_brl": 0.50,
        }
    ]
    with patch(
        "src.mcp.tools.get_geo_performance.run_report",
        AsyncMock(return_value=fake_rows),
    ):
        result = await get_geo_performance({"customer_id": "1234567890"})

    assert result["rows"][0]["country_criterion_id"] == "2076"


@pytest.mark.asyncio
async def test_hourly_performance_returns_rows(bound_context):
    from src.mcp.tools.get_hourly_performance import get_hourly_performance

    fake_rows = [
        {
            "hour": 14,
            "day_of_week": "MONDAY",
            "impressions": 500,
            "clicks": 25,
            "cost_brl": 12.50,
            "conversions": 1.0,
            "conversions_value_brl": 100.0,
            "ctr": 0.05,
            "cpc_brl": 0.50,
        }
    ]
    with patch(
        "src.mcp.tools.get_hourly_performance.run_report",
        AsyncMock(return_value=fake_rows),
    ):
        result = await get_hourly_performance({"customer_id": "1234567890"})

    assert result["rows"][0]["hour"] == 14
    assert result["rows"][0]["day_of_week"] == "MONDAY"
