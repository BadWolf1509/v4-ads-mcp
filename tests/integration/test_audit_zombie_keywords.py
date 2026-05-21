"""Integration tests for audit_zombie_keywords (Sprint 3b.36)."""

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
async def test_returns_zombies_shape(bound_context):
    """T1 cenário smoke: wire-up fake rows → response shape correto."""
    from src.mcp.tools.audit_zombie_keywords import audit_zombie_keywords

    fake_rows = [
        {
            "ad_group_id": "1001",
            "ad_group_name": "AG1",
            "campaign_name": "C1",
            "keyword_id": "K1",
            "keyword_text": "andaime metálico",
            "match_type": "BROAD",
            "impressions": 0,
            "clicks": 0,
            "cost_brl": 0.0,
            "conversions": 0,
            "status": "ENABLED",
        },
        {
            "ad_group_id": "1001",
            "ad_group_name": "AG1",
            "campaign_name": "C1",
            "keyword_id": "K2",
            "keyword_text": "andaime suspenso",
            "match_type": "PHRASE",
            "impressions": 0,
            "clicks": 0,
            "cost_brl": 0.0,
            "conversions": 0,
            "status": "ENABLED",
        },
    ]
    with patch(
        "src.mcp.tools.audit_zombie_keywords.run_report",
        AsyncMock(return_value=fake_rows),
    ):
        result = await audit_zombie_keywords({"customer_id": "1234567890"})

    assert result["customer_id"] == "1234567890"
    assert result["total_zombies"] == 2
    assert result["truncated"] is False
    assert result["returned_count"] == 2
    assert len(result["zombies"]) == 2
    # Sorted by ad_group_name + keyword_text ASC
    assert result["zombies"][0]["keyword_text"] == "andaime metálico"
    assert result["zombies"][1]["keyword_text"] == "andaime suspenso"


@pytest.mark.asyncio
async def test_ad_group_ids_filter_passthrough(bound_context):
    """T2 cenário smoke: ad_group_ids passa ao GAQL builder."""
    from src.mcp.tools.audit_zombie_keywords import audit_zombie_keywords

    captured_query: dict = {}

    async def fake_run_report(*args, **kwargs):
        captured_query["query"] = kwargs.get("query", "")
        return []

    with patch(
        "src.mcp.tools.audit_zombie_keywords.run_report",
        AsyncMock(side_effect=fake_run_report),
    ):
        await audit_zombie_keywords({"customer_id": "1234567890", "ad_group_ids": ["123", "456"]})

    assert "ad_group.id IN (123,456)" in captured_query["query"]


@pytest.mark.asyncio
async def test_truncation_when_total_exceeds_limit(bound_context):
    """T4 cenário smoke: 50 zombies + limit=10 → truncated=true."""
    from src.mcp.tools.audit_zombie_keywords import audit_zombie_keywords

    fake_rows = [
        {
            "ad_group_id": "1001",
            "ad_group_name": "AG1",
            "campaign_name": "C1",
            "keyword_id": f"K{i}",
            "keyword_text": f"kw_{i:03d}",
            "match_type": "BROAD",
            "impressions": 0,
            "clicks": 0,
            "cost_brl": 0.0,
            "conversions": 0,
            "status": "ENABLED",
        }
        for i in range(50)
    ]
    with patch(
        "src.mcp.tools.audit_zombie_keywords.run_report",
        AsyncMock(return_value=fake_rows),
    ):
        result = await audit_zombie_keywords({"customer_id": "1234567890", "limit": 10})

    assert result["total_zombies"] == 50
    assert result["truncated"] is True
    assert result["returned_count"] == 10
