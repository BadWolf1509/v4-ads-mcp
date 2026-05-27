"""Integration tests for get_keyword_performance (Sprint 3b.40 B9)."""

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
async def test_b9_negative_field_present_in_response(bound_context):
    """B9 (F56): cada row contém `negative: bool` field (true + false samples)."""
    from src.mcp.tools.get_keyword_performance import get_keyword_performance

    fake_rows = [
        {
            "criterion_id": "K1",
            "keyword_text": "gerador honda",
            "match_type": "BROAD",
            "status": "ENABLED",
            "negative": False,  # positive criterion
            "quality_score": 7,
            "quality_creative": "ABOVE_AVERAGE",
            "quality_post_click": "AVERAGE",
            "quality_search_predicted_ctr": "ABOVE_AVERAGE",
            "first_page_cpc_brl": 0.50,
            "top_of_page_cpc_brl": 1.20,
            "ad_group_id": "1001",
            "ad_group_name": "AG1",
            "campaign_id": "10",
            "campaign_name": "C1",
            "impressions": 100,
            "clicks": 10,
            "cost_brl": 5.00,
            "conversions": 1.0,
            "conversions_value_brl": 50.0,
            "ctr": 0.1,
            "cpc_brl": 0.50,
        },
        {
            "criterion_id": "K2",
            "keyword_text": "bobcat",
            "match_type": "BROAD",
            "status": "ENABLED",
            "negative": True,  # negative ad_group_criterion ENABLED
            "quality_score": None,
            "quality_creative": None,
            "quality_post_click": None,
            "quality_search_predicted_ctr": None,
            "first_page_cpc_brl": None,
            "top_of_page_cpc_brl": None,
            "ad_group_id": "1001",
            "ad_group_name": "AG1",
            "campaign_id": "10",
            "campaign_name": "C1",
            "impressions": 0,
            "clicks": 0,
            "cost_brl": 0.0,
            "conversions": 0.0,
            "conversions_value_brl": 0.0,
            "ctr": 0.0,
            "cpc_brl": 0.0,
        },
    ]

    with patch(
        "src.mcp.tools.get_keyword_performance.run_report",
        AsyncMock(return_value=fake_rows),
    ):
        result = await get_keyword_performance(
            {
                "customer_id": "1234567890",
                "date_range": "LAST_30_DAYS",
            }
        )

    assert result["customer_id"] == "1234567890"
    assert len(result["rows"]) == 2

    # B9 (F56): assert negative field present + correct type
    assert result["rows"][0]["negative"] is False
    assert result["rows"][1]["negative"] is True

    # Consumer-side filter pattern (F56 mitigation)
    positive_only = [r for r in result["rows"] if not r["negative"]]
    assert len(positive_only) == 1
    assert positive_only[0]["keyword_text"] == "gerador honda"
