"""Integration tests for the 6 tactical tools."""

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
async def test_keyword_performance_returns_qs(bound_context):
    from src.mcp.tools.get_keyword_performance import get_keyword_performance

    fake_rows = [
        {
            "criterion_id": "abc",
            "keyword_text": "v4 ads",
            "match_type": "EXACT",
            "status": "ENABLED",
            "quality_score": 8,
            "quality_creative": "ABOVE_AVERAGE",
            "quality_post_click": "AVERAGE",
            "quality_search_predicted_ctr": "ABOVE_AVERAGE",
            "first_page_cpc_brl": 0.50,
            "top_of_page_cpc_brl": 1.20,
            "ad_group_id": "g1",
            "ad_group_name": "Brand",
            "campaign_id": "c1",
            "campaign_name": "Brand",
            "impressions": 1000,
            "clicks": 50,
            "cost_brl": 25.0,
            "conversions": 5.0,
            "conversions_value_brl": 500.0,
            "ctr": 0.05,
            "cpc_brl": 0.50,
        }
    ]
    with patch(
        "src.mcp.tools.get_keyword_performance.run_report", AsyncMock(return_value=fake_rows)
    ):
        result = await get_keyword_performance({"customer_id": "1234567890"})
    assert result["rows"][0]["quality_score"] == 8
    assert result["rows"][0]["match_type"] == "EXACT"


@pytest.mark.asyncio
async def test_search_terms_report_includes_status(bound_context):
    from src.mcp.tools.get_search_terms_report import get_search_terms_report

    fake_rows = [
        {
            "search_term": "comprar v4",
            "status": "NONE",
            "ad_group_id": "g1",
            "ad_group_name": "Brand",
            "campaign_id": "c1",
            "campaign_name": "Brand",
            "impressions": 100,
            "clicks": 5,
            "cost_brl": 2.50,
            "conversions": 0.0,
            "conversions_value_brl": 0.0,
            "ctr": 0.05,
            "cpc_brl": 0.50,
        }
    ]
    with patch(
        "src.mcp.tools.get_search_terms_report.run_report", AsyncMock(return_value=fake_rows)
    ):
        result = await get_search_terms_report({"customer_id": "1234567890"})
    assert result["rows"][0]["search_term"] == "comprar v4"
    assert result["rows"][0]["status"] == "NONE"


@pytest.mark.asyncio
async def test_negative_keywords_audit_groups_by_campaign(bound_context):
    from src.mcp.tools.get_negative_keywords_audit import get_negative_keywords_audit

    fake_rows = [
        {
            "criterion_id": "n1",
            "keyword_text": "free",
            "match_type": "BROAD",
            "campaign_id": "c1",
            "campaign_name": "Brand",
        },
        {
            "criterion_id": "n2",
            "keyword_text": "barato",
            "match_type": "PHRASE",
            "campaign_id": "c1",
            "campaign_name": "Brand",
        },
        {
            "criterion_id": "n3",
            "keyword_text": "free",
            "match_type": "BROAD",
            "campaign_id": "c2",
            "campaign_name": "Performance",
        },
    ]
    mock_run = AsyncMock(side_effect=[fake_rows, []])  # negatives, then empty creates
    with patch("src.mcp.tools.get_negative_keywords_audit.run_report", mock_run):
        result = await get_negative_keywords_audit({"customer_id": "1234567890"})
    assert result["total_negatives"] == 3
    assert len(result["by_campaign"]) == 2
    brand = next(c for c in result["by_campaign"] if c["campaign_id"] == "c1")
    assert len(brand["negatives"]) == 2
    # Enriched fields present (no create events => all None)
    for camp in result["by_campaign"]:
        for n in camp["negatives"]:
            assert n["created_date"] is None
            assert n["added_by_email"] is None


@pytest.mark.asyncio
async def test_ad_performance_includes_headlines(bound_context):
    from src.mcp.tools.get_ad_performance import get_ad_performance

    fake_rows = [
        {
            "ad_id": "a1",
            "status": "ENABLED",
            "type": "RESPONSIVE_SEARCH_AD",
            "ad_strength": "GOOD",
            "headlines": ["V4 Ads", "Loja oficial", "Promocao"],
            "descriptions": ["Compre agora", "Frete gratis"],
            "final_urls": ["https://v4company.com"],
            "ad_group_id": "g1",
            "ad_group_name": "Brand",
            "campaign_id": "c1",
            "campaign_name": "Brand",
            "impressions": 5000,
            "clicks": 250,
            "cost_brl": 125.0,
            "conversions": 12.0,
            "conversions_value_brl": 2500.0,
            "ctr": 0.05,
            "cpc_brl": 0.50,
        }
    ]
    with patch("src.mcp.tools.get_ad_performance.run_report", AsyncMock(return_value=fake_rows)):
        result = await get_ad_performance({"customer_id": "1234567890"})
    assert result["rows"][0]["ad_strength"] == "GOOD"
    assert len(result["rows"][0]["headlines"]) == 3


@pytest.mark.asyncio
async def test_audience_performance_returns_rows(bound_context):
    from src.mcp.tools.get_audience_performance import get_audience_performance

    fake_rows = [
        {
            "resource_name": "customers/1234567890/adGroupAudienceViews/g1~a1",
            "criterion_id": "a1",
            "user_list": "customers/1234567890/userLists/100",
            "user_interest_category": None,
            "ad_group_id": "g1",
            "ad_group_name": "Brand",
            "campaign_id": "c1",
            "campaign_name": "Brand",
            "impressions": 5000,
            "clicks": 250,
            "cost_brl": 125.0,
            "conversions": 12.0,
            "conversions_value_brl": 2500.0,
            "ctr": 0.05,
            "cpc_brl": 0.50,
        }
    ]
    with patch(
        "src.mcp.tools.get_audience_performance.run_report", AsyncMock(return_value=fake_rows)
    ):
        result = await get_audience_performance({"customer_id": "1234567890"})
    assert len(result["rows"]) == 1
    assert result["rows"][0]["user_list"] is not None


@pytest.mark.asyncio
async def test_conversion_actions_returns_count(bound_context):
    from src.mcp.tools.get_conversion_actions import get_conversion_actions

    fake_rows = [
        {
            "id": "1",
            "name": "Purchase",
            "status": "ENABLED",
            "category": "PURCHASE",
            "type": "WEBPAGE",
            "counting_type": "ONE_PER_CLICK",
            "attribution_model": "DATA_DRIVEN",
            "default_value_brl": 0.0,
            "always_use_default_value": False,
            "primary_for_goal": True,
            "include_in_conversions_metric": True,
        },
    ]
    with patch(
        "src.mcp.tools.get_conversion_actions.run_report", AsyncMock(return_value=fake_rows)
    ):
        result = await get_conversion_actions({"customer_id": "1234567890"})
    assert result["count"] == 1
    assert result["actions"][0]["name"] == "Purchase"
    assert result["actions"][0]["primary_for_goal"] is True
    assert result["actions"][0]["include_in_conversions_metric"] is True
