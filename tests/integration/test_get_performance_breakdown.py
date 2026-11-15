from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_campaign_level_happy(ctx_mcp):
    from src.mcp.tools.get_performance_breakdown import get_performance_breakdown

    fake_rows = [{"campaign_id": "10", "cost_brl": 5.0}]
    with patch(
        "src.mcp.tools.get_performance_breakdown.run_report",
        AsyncMock(return_value=fake_rows),
    ):
        out = await get_performance_breakdown({"customer_id": "1234567890", "level": "campaign"})
    assert out["level"] == "campaign"
    assert out["rows"] == fake_rows


@pytest.mark.asyncio
async def test_invalid_combo_account_without_breakdown(ctx_mcp):
    from src.mcp.tools.get_performance_breakdown import get_performance_breakdown

    out = await get_performance_breakdown({"customer_id": "1234567890", "level": "account"})
    assert out["status"] == "error"
    assert "get_account_overview" in out["error_message"]


@pytest.mark.asyncio
async def test_geo_breakdown_enriches_country(ctx_mcp):
    from src.mcp.tools.get_performance_breakdown import get_performance_breakdown

    fake_rows = [{"breakdown": {"country_criterion_id": "2076"}, "cost_brl": 1.0}]
    with (
        patch(
            "src.mcp.tools.get_performance_breakdown.run_report",
            AsyncMock(return_value=fake_rows),
        ),
        patch(
            "src.mcp.tools.get_performance_breakdown.lookup_country_names",
            AsyncMock(return_value={"2076": {"name": "Brasil", "country_code": "BR"}}),
        ),
    ):
        out = await get_performance_breakdown(
            {"customer_id": "1234567890", "level": "account", "breakdown": "geo"}
        )
    assert out["rows"][0]["breakdown"]["country_name"] == "Brasil"
    assert out["rows"][0]["breakdown"]["country_code"] == "BR"
