"""Unit tests for get_negative_keywords_audit enrichment + summary logic (Sprint 3b.21)."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from freezegun import freeze_time

from src.mcp.context import McpRequestContext, clear_current, set_current
from src.mcp.tools.get_negative_keywords_audit import get_negative_keywords_audit


def _negative_row(criterion_id: str, campaign_id: str = "1001", campaign_name: str = "Camp A"):
    """Build a fake row matching `_row_formatter` shape for the negative query."""
    return {
        "criterion_id": criterion_id,
        "keyword_text": f"negativa-{criterion_id}",
        "match_type": "BROAD",
        "campaign_id": campaign_id,
        "campaign_name": campaign_name,
    }


def _create_event(criterion_id: str, when: str, email: str, campaign_id: str = "1001"):
    """Build a fake row matching the change_event CREATE event shape."""
    return {
        "change_resource_name": f"customers/9999999999/campaignCriteria/{campaign_id}~{criterion_id}",
        "change_date_time": when,
        "user_email": email,
    }


@pytest.fixture(autouse=True)
def _ctx():
    """Bind a dummy manager context (handler reads ctx.manager_id + ctx.session_id)."""
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


@freeze_time("2026-05-17")
@pytest.mark.asyncio
async def test_audit_enriches_per_criterion_when_match_exists():
    with patch(
        "src.mcp.tools.get_negative_keywords_audit.run_report", new_callable=AsyncMock
    ) as mock_run:
        mock_run.side_effect = [
            # Query A — negatives
            [_negative_row("111"), _negative_row("222")],
            # Query B — CREATE events (only criterion 111 has a recent CREATE)
            [_create_event("111", "2026-05-10 14:30:00+00:00", "wellinton.ribeiro@v4company.com")],
        ]
        result = await get_negative_keywords_audit({"customer_id": "9999999999"})

    by_campaign = result["by_campaign"]
    assert len(by_campaign) == 1
    negatives = {n["criterion_id"]: n for n in by_campaign[0]["negatives"]}
    assert negatives["111"]["created_date"] == "2026-05-10"
    assert negatives["111"]["added_by_email"] == "wellinton.ribeiro@v4company.com"
    assert negatives["222"]["created_date"] is None
    assert negatives["222"]["added_by_email"] is None


@freeze_time("2026-05-17")
@pytest.mark.asyncio
async def test_audit_summary_counts_three_buckets():
    with patch(
        "src.mcp.tools.get_negative_keywords_audit.run_report", new_callable=AsyncMock
    ) as mock_run:
        mock_run.side_effect = [
            # 5 negatives
            [_negative_row(str(i)) for i in range(1, 6)],
            # CREATEs: 1 last_7_days (criterion 1), 1 between 7-30d (criterion 2), 3 not in change_event
            [
                _create_event(
                    "1", "2026-05-15 10:00:00+00:00", "user@v4.com"
                ),  # 2 days ago = last_7
                _create_event(
                    "2", "2026-04-25 10:00:00+00:00", "user@v4.com"
                ),  # 22 days ago = last_30 only
            ],
        ]
        result = await get_negative_keywords_audit({"customer_id": "9999999999"})

    s = result["additions_summary"]
    assert s["last_7_days"] == 1
    assert s["last_30_days"] == 2
    assert s["pre_30_days_or_unknown"] == 3
    # Invariant
    assert s["last_30_days"] + s["pre_30_days_or_unknown"] == result["total_negatives"]
    assert s["last_7_days"] <= s["last_30_days"]


@freeze_time("2026-05-17")
@pytest.mark.asyncio
async def test_audit_picks_most_recent_create_when_duplicates():
    """If change_event has 2 CREATE events for same criterion_id, pick the most recent."""
    with patch(
        "src.mcp.tools.get_negative_keywords_audit.run_report", new_callable=AsyncMock
    ) as mock_run:
        mock_run.side_effect = [
            [_negative_row("777")],
            [
                _create_event("777", "2026-05-01 10:00:00+00:00", "older@v4.com"),
                _create_event("777", "2026-05-14 10:00:00+00:00", "newer@v4.com"),
            ],
        ]
        result = await get_negative_keywords_audit({"customer_id": "9999999999"})

    neg = result["by_campaign"][0]["negatives"][0]
    assert neg["created_date"] == "2026-05-14"
    assert neg["added_by_email"] == "newer@v4.com"


@freeze_time("2026-05-17")
@pytest.mark.asyncio
async def test_audit_handles_empty_change_event_result():
    with patch(
        "src.mcp.tools.get_negative_keywords_audit.run_report", new_callable=AsyncMock
    ) as mock_run:
        mock_run.side_effect = [
            [_negative_row("111"), _negative_row("222")],
            [],  # No CREATEs in last 30d
        ]
        result = await get_negative_keywords_audit({"customer_id": "9999999999"})

    s = result["additions_summary"]
    assert s["last_7_days"] == 0
    assert s["last_30_days"] == 0
    assert s["pre_30_days_or_unknown"] == 2
    for camp in result["by_campaign"]:
        for n in camp["negatives"]:
            assert n["created_date"] is None
            assert n["added_by_email"] is None


@freeze_time("2026-05-17")
@pytest.mark.asyncio
async def test_audit_handles_empty_negatives_result():
    with patch(
        "src.mcp.tools.get_negative_keywords_audit.run_report", new_callable=AsyncMock
    ) as mock_run:
        mock_run.side_effect = [[], []]
        result = await get_negative_keywords_audit({"customer_id": "9999999999"})

    assert result["total_negatives"] == 0
    assert result["by_campaign"] == []
    assert result["additions_summary"] == {
        "last_7_days": 0,
        "last_30_days": 0,
        "pre_30_days_or_unknown": 0,
    }


@freeze_time("2026-05-17")
@pytest.mark.asyncio
async def test_audit_ignores_create_events_for_criteria_not_in_current_state():
    """change_event may have CREATEs for criteria that were later REMOVED — those
    don't appear in Query A's current state. Tool must not surface them."""
    with patch(
        "src.mcp.tools.get_negative_keywords_audit.run_report", new_callable=AsyncMock
    ) as mock_run:
        mock_run.side_effect = [
            [_negative_row("111")],
            [
                _create_event("111", "2026-05-15 10:00:00+00:00", "user@v4.com"),
                _create_event("999", "2026-05-15 10:00:00+00:00", "user@v4.com"),  # orphan
            ],
        ]
        result = await get_negative_keywords_audit({"customer_id": "9999999999"})

    assert result["total_negatives"] == 1
    assert len(result["by_campaign"][0]["negatives"]) == 1
    assert result["additions_summary"]["last_7_days"] == 1  # criterion 999 doesn't count
