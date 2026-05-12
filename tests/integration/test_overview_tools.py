"""Integration tests for the 3 visao geral tools.

Strategy: patch run_report to return fixture rows, then assert the
tool's aggregate/format logic produces the expected response shape.
"""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from freezegun import freeze_time

from src.mcp.context import McpRequestContext, clear_current, set_current


@pytest.fixture
def bound_context():
    ctx = McpRequestContext(manager_id=uuid4(), session_id=uuid4())
    set_current(ctx)
    yield ctx
    clear_current()


@pytest.mark.asyncio
@freeze_time("2026-05-15")
@pytest.mark.integration
async def test_account_overview_aggregates_and_compares(bound_context):
    from src.mcp.tools.get_account_overview import get_account_overview

    side_effects = [
        # current period rows
        [
            {
                "impressions": 1000,
                "clicks": 50,
                "cost_micros": 100_000_000,
                "conversions": 5.0,
                "conversions_value": 500.0,
            },
            {
                "impressions": 2000,
                "clicks": 100,
                "cost_micros": 200_000_000,
                "conversions": 10.0,
                "conversions_value": 1000.0,
            },
        ],
        # previous period rows
        [
            {
                "impressions": 1500,
                "clicks": 75,
                "cost_micros": 150_000_000,
                "conversions": 7.0,
                "conversions_value": 700.0,
            },
        ],
    ]
    with patch(
        "src.mcp.tools.get_account_overview.run_report",
        AsyncMock(side_effect=side_effects),
    ):
        result = await get_account_overview(
            {
                "customer_id": "1234567890",
                "date_range": "LAST_7_DAYS",
            }
        )

    assert result["customer_id"] == "1234567890"
    assert result["period"] == {"from": "2026-05-08", "to": "2026-05-14"}
    assert result["previous_period"] == {"from": "2026-05-01", "to": "2026-05-07"}
    cur = result["current"]
    assert cur["impressions"] == 3000
    assert cur["clicks"] == 150
    assert cur["cost_brl"] == 300.0
    assert cur["conversions"] == 15.0
    assert cur["roas"] == round(1500.0 / 300.0, 2)
    prev = result["previous"]
    assert prev["impressions"] == 1500


@pytest.mark.asyncio
async def test_account_overview_handles_zero_division(bound_context):
    from src.mcp.tools.get_account_overview import get_account_overview

    with patch(
        "src.mcp.tools.get_account_overview.run_report",
        AsyncMock(return_value=[]),
    ):
        result = await get_account_overview({"customer_id": "1234567890"})

    cur = result["current"]
    assert cur["impressions"] == 0
    assert cur["ctr"] == 0.0
    assert cur["roas"] == 0.0


@pytest.mark.asyncio
@freeze_time("2026-05-15 12:00:00")
async def test_budget_pacing_projects_monthly(bound_context):
    from src.mcp.tools.get_budget_pacing import get_budget_pacing

    rows = [
        {
            "campaign_id": "111",
            "campaign_name": "Campaign A",
            "daily_budget_brl": 100.0,
            "delivery_method": "STANDARD",
            "cost_micros_today": 50_000_000,
        },
    ]
    with patch(
        "src.mcp.tools.get_budget_pacing.run_report",
        AsyncMock(return_value=rows),
    ):
        result = await get_budget_pacing({"customer_id": "1234567890"})

    assert len(result["campaigns"]) == 1
    c = result["campaigns"][0]
    assert c["campaign_id"] == "111"
    assert c["spent_mtd_brl"] == 50.0
    assert c["days_elapsed"] == 15
    # 50 BRL in 15 days = 3.33/day; projected for 31 days ≈ 103 BRL
    assert 99 <= c["projected_monthly_brl"] <= 110


@pytest.mark.asyncio
async def test_recommendations_translates_known_types(bound_context):
    from src.mcp.tools.get_recommendations import get_recommendations

    fake_row = {
        "resource_name": "customers/1234567890/recommendations/abc",
        "type": "KEYWORD",
        "type_pt": "Adicionar palavra-chave",
        "current_clicks": 100,
        "current_impressions": 5000,
        "current_cost_brl": 50.0,
        "potential_clicks": 150,
        "potential_impressions": 7500,
        "potential_cost_brl": 75.0,
        "uplift_clicks": 50,
        "uplift_impressions": 2500,
    }
    with patch(
        "src.mcp.tools.get_recommendations.run_report",
        AsyncMock(return_value=[fake_row]),
    ):
        result = await get_recommendations({"customer_id": "1234567890"})

    assert result["count"] == 1
    rec = result["recommendations"][0]
    assert rec["type_pt"] == "Adicionar palavra-chave"
    assert rec["uplift_clicks"] == 50


@pytest.mark.asyncio
async def test_invalid_customer_id_format_in_schema(bound_context):
    from src.mcp.tools.get_account_overview import _SCHEMA

    assert _SCHEMA["properties"]["customer_id"]["pattern"] == "^[0-9]{10}$"
