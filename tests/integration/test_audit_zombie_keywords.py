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
            "ad_group_status": "ENABLED",
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
            "ad_group_status": "ENABLED",
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
    assert result["zombies"][0]["ad_group_status"] == "ENABLED"  # F52
    assert result["zombies"][1]["keyword_text"] == "andaime suspenso"
    assert result["zombies"][1]["ad_group_status"] == "ENABLED"  # F52


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
            "ad_group_status": "ENABLED",
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


@pytest.mark.asyncio
async def test_f52_orphan_keywords_in_removed_ad_groups_exposed(bound_context):
    """F52 regression: keywords ENABLED em ad_groups REMOVED appear with
    ad_group_status='REMOVED' na response, permitting consumer-side filter.

    Dogfood 2026-05-25 MO-JP+CAB: tool retornou 280 zumbis mas 170 (60.7%)
    eram órfãs cosméticas em DELL JPA (93) + GPA02 ANDAIME CAB (77).
    Consumer agora pode filtrar `ad_group_status == 'ENABLED'` pra cleanup
    de impacto técnico real, OU manter tudo pra inventário cosmético.
    """
    from src.mcp.tools.audit_zombie_keywords import audit_zombie_keywords

    fake_rows = [
        {
            "ad_group_id": "2001",
            "ad_group_name": "GPA01_GERAL",
            "ad_group_status": "ENABLED",  # impactável
            "campaign_name": "GPA",
            "keyword_id": "K1",
            "keyword_text": "alpha",
            "match_type": "BROAD",
            "impressions": 0,
            "clicks": 0,
            "cost_brl": 0.0,
            "conversions": 0,
            "status": "ENABLED",
        },
        {
            "ad_group_id": "174842025340",
            "ad_group_name": "DELL",
            "ad_group_status": "REMOVED",  # órfã cosmética
            "campaign_name": "JPA",
            "keyword_id": "K2",
            "keyword_text": "beta",
            "match_type": "BROAD",
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

    assert result["total_zombies"] == 2
    # Sorted by ad_group_name ASC: DELL antes de GPA01_GERAL
    assert result["zombies"][0]["ad_group_name"] == "DELL"
    assert result["zombies"][0]["ad_group_status"] == "REMOVED"
    assert result["zombies"][1]["ad_group_name"] == "GPA01_GERAL"
    assert result["zombies"][1]["ad_group_status"] == "ENABLED"

    # Consumer-side filter pattern documented em description F52
    impactable = [z for z in result["zombies"] if z["ad_group_status"] == "ENABLED"]
    assert len(impactable) == 1
    assert impactable[0]["keyword_text"] == "alpha"
