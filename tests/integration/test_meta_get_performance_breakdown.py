"""Integration tests Sprint M.4: meta_get_performance_breakdown."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from tests.integration._seed import seed_manager, seed_meta_account

pytestmark = pytest.mark.asyncio


async def _seed(db):
    async with db.acquire() as conn:
        mid = await seed_manager(conn)
        await seed_meta_account(conn, mid)
    return mid


@pytest.mark.integration
async def test_happy_path_platform_breakdown_sorted_and_surfaced(db):
    from src.mcp.tools.meta_get_performance_breakdown import meta_get_performance_breakdown

    mid = await _seed(db)
    body = {
        "data": [
            {
                "campaign_id": "c1",
                "campaign_name": "C1",
                "spend": "100",
                "publisher_platform": "facebook",
            },
            {
                "campaign_id": "c1",
                "campaign_name": "C1",
                "spend": "300",
                "publisher_platform": "instagram",
            },
        ]
    }
    with patch(
        "src.mcp.tools.meta_get_performance_breakdown.run_meta_graph_get",
        new=AsyncMock(return_value=body),
    ):
        result = await meta_get_performance_breakdown(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
            breakdown="platform",
            date_range="LAST_7_DAYS",
        )
    assert result["status"] == "success"
    assert result["level"] == "campaign"
    assert result["breakdown"] == "platform"
    assert result["total_rows"] == 2
    assert result["rows"][0]["breakdown"] == {"publisher_platform": "instagram"}  # 300 first
    assert result["rows"][1]["breakdown"] == {"publisher_platform": "facebook"}


@pytest.mark.integration
async def test_injects_breakdowns_param_for_level(db):
    from src.mcp.tools.meta_get_performance_breakdown import meta_get_performance_breakdown

    mid = await _seed(db)
    captured: dict = {}

    async def capture(**kwargs):
        captured.update(kwargs["params"])
        return {"data": []}

    with patch(
        "src.mcp.tools.meta_get_performance_breakdown.run_meta_graph_get",
        new=AsyncMock(side_effect=capture),
    ):
        await meta_get_performance_breakdown(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
            breakdown="hourly",
            level="adset",
        )
    assert captured["level"] == "adset"
    assert captured["breakdowns"] == "hourly_stats_aggregated_by_advertiser_time_zone"


@pytest.mark.integration
async def test_account_not_found_returns_error(db):
    from src.mcp.tools.meta_get_performance_breakdown import meta_get_performance_breakdown

    async with db.acquire() as conn:
        mid = await seed_manager(conn)

    result = await meta_get_performance_breakdown(
        manager_id=mid,
        session_id=uuid4(),
        ad_account_id="act_999999",
        breakdown="platform",
    )
    assert result["status"] == "error"
    assert "act_999999" in result["error_message"]
    assert "não está no inventário" in result["error_message"]


@pytest.mark.integration
async def test_meta_api_error_returns_friendly_pt_br(db):
    from src.mcp.tools.meta_get_performance_breakdown import meta_get_performance_breakdown
    from src.meta_ads.errors import MetaAdsFriendlyError

    mid = await _seed(db)
    with patch(
        "src.mcp.tools.meta_get_performance_breakdown.run_meta_graph_get",
        new=AsyncMock(side_effect=MetaAdsFriendlyError("Limite Meta atingido.", retryable=True)),
    ):
        result = await meta_get_performance_breakdown(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
            breakdown="geo",
        )
    assert result["status"] == "error"
    assert "Limite Meta" in result["error_message"]
