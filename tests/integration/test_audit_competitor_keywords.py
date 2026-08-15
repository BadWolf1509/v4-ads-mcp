"""Integration tests for audit_competitor_keywords (Sprint 3b.31)."""

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
async def test_returns_full_shape_with_matched_brands(bound_context):
    """Wire-up: fake rows → output shape match spec section 3.2."""
    from src.mcp.tools.audit_competitor_keywords import audit_competitor_keywords

    fake_pos_rows = [
        {
            "ad_group_id": "1001",
            "ad_group_name": "AG1",
            "campaign_name": "C1",
            "keyword_id": "K1",
            "keyword_text": "comprar projecta",
            "match_type": "BROAD",
            # F90: o parser agora le o status do ad_group PAI — keyword
            # ENABLED em ad_group REMOVED nao compete e nao gasta.
            "ad_group_status": "ENABLED",
        },
    ]
    fake_st_rows = [
        {
            "search_term": "gerador projecta 5500",
            "ad_group_name": "AG1",
            "campaign_name": "C1",
            "impressions": 142,
            "clicks": 5,
            "cost_brl": 42.30,
        },
        {
            "search_term": "projecta promoção",
            "ad_group_name": "AG1",
            "campaign_name": "C1",
            "impressions": 50,
            "clicks": 2,
            "cost_brl": 15.00,
        },
    ]

    mock_run = AsyncMock(side_effect=[fake_pos_rows, fake_st_rows])
    with patch("src.mcp.tools.audit_competitor_keywords.run_report", mock_run):
        result = await audit_competitor_keywords(
            {
                "customer_id": "1234567890",
                "competitor_brands": ["projecta"],
                "date_range": "LAST_7_DAYS",
            }
        )

    assert result["customer_id"] == "1234567890"
    assert result["competitor_brands"] == ["projecta"]
    assert result["summary"]["positive_keywords_count"] == 1
    assert result["summary"]["search_terms_count"] == 2
    assert result["summary"]["total_cost_wasted_brl"] == 57.30
    assert result["summary"]["suggested_negatives_count"] == 2
    assert len(result["positive_keywords"]) == 1
    assert result["positive_keywords"][0]["matched_brand"] == "projecta"
    assert len(result["search_terms"]) == 2
    assert result["search_terms"][0]["cost_brl"] == 42.30
    assert result["search_terms"][1]["cost_brl"] == 15.00
    assert result["suggested_negatives"][0]["match_type"] == "EXACT"
    assert result["suggested_negatives"][1]["match_type"] == "PHRASE"


@pytest.mark.asyncio
async def test_audit_this_call_true_in_both_calls(bound_context):
    """Verify ambas chamadas run_report têm audit_this_call=True."""
    from src.mcp.tools.audit_competitor_keywords import audit_competitor_keywords

    mock_run = AsyncMock(return_value=[])
    with patch("src.mcp.tools.audit_competitor_keywords.run_report", mock_run):
        await audit_competitor_keywords(
            {
                "customer_id": "1234567890",
                "competitor_brands": ["projecta"],
                "date_range": "LAST_7_DAYS",
            }
        )

    assert mock_run.call_count == 2
    for call in mock_run.call_args_list:
        kwargs = call.kwargs
        assert kwargs["audit_this_call"] is True
        assert kwargs["operation_name"] == "audit_competitor_keywords"


@pytest.mark.asyncio
async def test_2_queries_called_in_parallel_via_gather(bound_context):
    """Verify ambas queries chamadas (asyncio.gather usado em paralelo)."""
    from src.mcp.tools.audit_competitor_keywords import audit_competitor_keywords

    mock_run = AsyncMock(return_value=[])
    with patch("src.mcp.tools.audit_competitor_keywords.run_report", mock_run):
        await audit_competitor_keywords(
            {
                "customer_id": "1234567890",
                "competitor_brands": ["projecta"],
                "date_range": "LAST_7_DAYS",
            }
        )

    assert mock_run.call_count == 2
    queries_called = [call.kwargs["query"] for call in mock_run.call_args_list]
    assert any("keyword_view" in q for q in queries_called)
    assert any("search_term_view" in q for q in queries_called)
