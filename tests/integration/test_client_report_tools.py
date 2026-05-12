"""Integration tests for client report tools."""

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
@pytest.mark.integration
async def test_funnel_metrics_computes_rates(bound_context):
    from src.mcp.tools.get_funnel_metrics import get_funnel_metrics

    fake_rows = [
        {
            "impressions": 10000,
            "clicks": 500,
            "cost_micros": 500_000_000,
            "conversions": 25.0,
            "conversions_value": 5000.0,
        },
    ]
    with patch("src.mcp.tools.get_funnel_metrics.run_report", AsyncMock(return_value=fake_rows)):
        result = await get_funnel_metrics({"customer_id": "1234567890"})
    funnel = result["funnel"]
    assert funnel["stages"][0]["value"] == 10000
    assert funnel["stages"][1]["value"] == 500
    assert funnel["stages"][1]["rate_from_prev_pct"] == 5.0  # 500/10000
    assert funnel["stages"][2]["value"] == 25.0
    assert funnel["stages"][2]["rate_from_prev_pct"] == 5.0  # 25/500
    assert funnel["totals"]["cost_brl"] == 500.0
    assert funnel["totals"]["roas"] == 10.0  # 5000 / 500
    assert funnel["totals"]["cost_per_conversion_brl"] == 20.0  # 500 / 25


@pytest.mark.asyncio
async def test_funnel_handles_empty_data(bound_context):
    from src.mcp.tools.get_funnel_metrics import get_funnel_metrics

    with patch("src.mcp.tools.get_funnel_metrics.run_report", AsyncMock(return_value=[])):
        result = await get_funnel_metrics({"customer_id": "1234567890"})
    assert result["funnel"]["stages"][0]["value"] == 0
    assert result["funnel"]["totals"]["roas"] == 0.0


@pytest.mark.asyncio
async def test_top_keywords_creatives_default_metric_cost(bound_context):
    from src.mcp.tools.get_top_keywords_creatives import get_top_keywords_creatives

    fake_kws = [
        {
            "criterion_id": "k1",
            "keyword_text": "v4",
            "match_type": "EXACT",
            "campaign_name": "Brand",
            "ad_group_name": "Brand",
            "impressions": 1000,
            "clicks": 50,
            "cost_brl": 25.0,
            "conversions": 5.0,
            "conversions_value_brl": 500.0,
        },
    ]
    fake_ads = [
        {
            "ad_id": "a1",
            "headlines": ["V4 Ads"],
            "descriptions": ["Compre"],
            "ad_strength": "GOOD",
            "campaign_name": "Brand",
            "ad_group_name": "Brand",
            "impressions": 5000,
            "clicks": 250,
            "cost_brl": 125.0,
            "conversions": 12.0,
            "conversions_value_brl": 2500.0,
        },
    ]
    side_effects = [fake_kws, fake_ads]
    with patch(
        "src.mcp.tools.get_top_keywords_creatives.run_report",
        AsyncMock(side_effect=side_effects),
    ):
        result = await get_top_keywords_creatives(
            {
                "customer_id": "1234567890",
                "top_n": 5,
            }
        )
    assert result["metric"] == "cost"
    assert len(result["top_keywords"]) == 1
    assert len(result["top_creatives"]) == 1


@pytest.mark.asyncio
async def test_top_keywords_creatives_custom_metric_resorts(bound_context):
    from src.mcp.tools.get_top_keywords_creatives import get_top_keywords_creatives

    # Returned ORDER BY cost: high-cost first. With metric=conversions, low-cost
    # high-conversion entry should rank above.
    fake_kws = [
        {
            "criterion_id": "k1",
            "keyword_text": "expensive_low_conv",
            "match_type": "EXACT",
            "campaign_name": "X",
            "ad_group_name": "Y",
            "impressions": 100,
            "clicks": 50,
            "cost_brl": 100.0,
            "conversions": 1.0,
            "conversions_value_brl": 50.0,
        },
        {
            "criterion_id": "k2",
            "keyword_text": "cheap_high_conv",
            "match_type": "EXACT",
            "campaign_name": "X",
            "ad_group_name": "Y",
            "impressions": 100,
            "clicks": 50,
            "cost_brl": 10.0,
            "conversions": 20.0,
            "conversions_value_brl": 1000.0,
        },
    ]
    fake_ads = []
    with patch(
        "src.mcp.tools.get_top_keywords_creatives.run_report",
        AsyncMock(side_effect=[fake_kws, fake_ads]),
    ):
        result = await get_top_keywords_creatives(
            {
                "customer_id": "1234567890",
                "metric": "conversions",
            }
        )
    # Should be re-sorted so cheap_high_conv is first
    assert result["top_keywords"][0]["keyword_text"] == "cheap_high_conv"
