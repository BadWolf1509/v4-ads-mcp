"""Integration tests for audit_quality_score (Sprint 3b.30)."""

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
async def test_returns_flagged_keywords_shape(bound_context):
    """Wire-up: fake rows → output matches spec section 3.2."""
    from src.mcp.tools.audit_quality_score import audit_quality_score

    fake_rows = [
        {
            "ad_group_id": "1001",
            "ad_group_name": "AG1",
            "ad_group_status": "ENABLED",
            "campaign_name": "C1",
            "keyword_id": "K1",
            "keyword_text": "gerador energia",
            "match_type": "BROAD",
            "quality_score": 2,
            "impressions": 50,
            "clicks": 0,
            "conversions": 0,
            "cost_brl": 0.0,
        },
        {
            "ad_group_id": "1002",
            "ad_group_name": "AG2",
            "ad_group_status": "ENABLED",
            "campaign_name": "C1",
            "keyword_id": "K2",
            "keyword_text": "gerador honda",
            "match_type": "BROAD",
            "quality_score": 8,
            "impressions": 100,
            "clicks": 10,
            "conversions": 2,
            "cost_brl": 15.50,
        },
    ]

    with patch(
        "src.mcp.tools.audit_quality_score.run_report",
        AsyncMock(return_value=fake_rows),
    ):
        result = await audit_quality_score(
            {
                "customer_id": "1234567890",
                "date_range": "LAST_30_DAYS",
            }
        )

    assert result["customer_id"] == "1234567890"
    assert "date_range_resolved" in result
    assert result["date_range_resolved"]["days"] >= 28  # LAST_30_DAYS ~30
    assert result["total_flagged"] == 2
    assert result["truncated"] is False
    assert len(result["flagged_keywords"]) == 2
    # Order: QS 2 first (candidate_pause), QS 8 second (candidate_promote_exact)
    assert result["flagged_keywords"][0]["quality_score"] == 2
    assert "candidate_pause" in result["flagged_keywords"][0]["flags"]
    assert result["flagged_keywords"][1]["quality_score"] == 8
    assert "candidate_promote_exact" in result["flagged_keywords"][1]["flags"]


@pytest.mark.asyncio
async def test_audit_this_call_true_logs_to_audit(bound_context):
    """Verify run_report called with audit_this_call=True (sensitive read)."""
    from src.mcp.tools.audit_quality_score import audit_quality_score

    mock_run = AsyncMock(return_value=[])
    with patch("src.mcp.tools.audit_quality_score.run_report", mock_run):
        await audit_quality_score({"customer_id": "1234567890", "date_range": "LAST_7_DAYS"})

    # Inspect run_report call kwargs
    call_kwargs = mock_run.call_args.kwargs
    assert call_kwargs["audit_this_call"] is True
    assert call_kwargs["operation_name"] == "audit_quality_score"
    assert "min_impressions" in call_kwargs["params_summary"]


@pytest.mark.asyncio
async def test_respects_min_impressions_threshold(bound_context):
    """min_impressions=50 → only flag candidate_pause em kw com imp >= 50."""
    from src.mcp.tools.audit_quality_score import audit_quality_score

    fake_rows = [
        # imp 20 < threshold 50 → NOT flagged
        {
            "ad_group_id": "1001",
            "ad_group_name": "AG1",
            "ad_group_status": "ENABLED",
            "campaign_name": "C1",
            "keyword_id": "K1",
            "keyword_text": "kw_low",
            "match_type": "BROAD",
            "quality_score": 1,
            "impressions": 20,
            "clicks": 0,
            "conversions": 0,
            "cost_brl": 0.0,
        },
        # imp 100 > threshold 50 → flagged
        {
            "ad_group_id": "1001",
            "ad_group_name": "AG1",
            "ad_group_status": "ENABLED",
            "campaign_name": "C1",
            "keyword_id": "K2",
            "keyword_text": "kw_high",
            "match_type": "BROAD",
            "quality_score": 1,
            "impressions": 100,
            "clicks": 0,
            "conversions": 0,
            "cost_brl": 0.0,
        },
    ]

    with patch(
        "src.mcp.tools.audit_quality_score.run_report",
        AsyncMock(return_value=fake_rows),
    ):
        result = await audit_quality_score(
            {
                "customer_id": "1234567890",
                "min_impressions": 50,
                "date_range": "LAST_30_DAYS",
            }
        )

    assert result["total_flagged"] == 1
    assert result["flagged_keywords"][0]["keyword_text"] == "kw_high"


@pytest.mark.asyncio
async def test_a2_orphan_keywords_in_removed_ad_groups_exposed(bound_context):
    """A2 (espelha F52): keywords flagged em ad_groups REMOVED appear with
    ad_group_status='REMOVED' na response, permitting consumer-side filter.

    Pattern idêntico ao F52 regression em audit_zombie_keywords (dogfood
    2026-05-25). Consumer pode filtrar `ad_group_status == 'ENABLED'` pra
    cleanup de impacto técnico real, OU manter tudo pra inventário cosmético.
    """
    from src.mcp.tools.audit_quality_score import audit_quality_score

    fake_rows = [
        {
            "ad_group_id": "2001",
            "ad_group_name": "GPA01_GERAL",
            "ad_group_status": "ENABLED",  # impactável
            "campaign_name": "GPA",
            "keyword_id": "K1",
            "keyword_text": "alpha",
            "match_type": "BROAD",
            "quality_score": 2,
            "impressions": 50,
            "clicks": 0,
            "conversions": 0,
            "cost_brl": 0.0,
        },
        {
            "ad_group_id": "174842025340",
            "ad_group_name": "DELL",
            "ad_group_status": "REMOVED",  # órfã cosmética
            "campaign_name": "JPA",
            "keyword_id": "K2",
            "keyword_text": "beta",
            "match_type": "BROAD",
            "quality_score": 1,
            "impressions": 30,
            "clicks": 0,
            "conversions": 0,
            "cost_brl": 0.0,
        },
    ]
    with patch(
        "src.mcp.tools.audit_quality_score.run_report",
        AsyncMock(return_value=fake_rows),
    ):
        result = await audit_quality_score({"customer_id": "1234567890"})

    assert result["total_flagged"] == 2
    # Sorted by QS ASC (1 antes de 2), so K2/DELL first
    assert result["flagged_keywords"][0]["ad_group_name"] == "DELL"
    assert result["flagged_keywords"][0]["ad_group_status"] == "REMOVED"
    assert result["flagged_keywords"][1]["ad_group_name"] == "GPA01_GERAL"
    assert result["flagged_keywords"][1]["ad_group_status"] == "ENABLED"

    # Consumer-side filter pattern documented em description A2
    impactable = [k for k in result["flagged_keywords"] if k["ad_group_status"] == "ENABLED"]
    assert len(impactable) == 1
    assert impactable[0]["keyword_text"] == "alpha"
