"""Integration tests for audit_orphan_smart_actions (Sprint 3b.37)."""

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
async def test_returns_orphans_shape(bound_context):
    """T1 cenário smoke: wire-up fake rows → response shape correto."""
    from src.mcp.tools.audit_orphan_smart_actions import audit_orphan_smart_actions

    fake_rows = [
        {
            "conversion_action_id": "1001",
            "name": "Whatsapp - Antigo",
            "category": "CONTACT",
            "origin": "WEBSITE",
            "primary_for_goal": True,
            "status": "ENABLED",
            "all_conversions": 0.0,
        },
        {
            "conversion_action_id": "1002",
            "name": "Email Form",
            "category": "CONTACT",
            "origin": "WEBSITE",
            "primary_for_goal": False,
            "status": "ENABLED",
            "all_conversions": 0.0,
        },
    ]
    with patch(
        "src.mcp.tools.audit_orphan_smart_actions.run_report",
        AsyncMock(return_value=fake_rows),
    ):
        result = await audit_orphan_smart_actions({"customer_id": "1234567890"})

    assert result["customer_id"] == "1234567890"
    assert result["total_orphans"] == 2
    assert result["truncated"] is False
    assert result["returned_count"] == 2
    assert len(result["orphans"]) == 2
    # Sorted by category, origin, name ASC
    assert result["orphans"][0]["name"] == "Email Form"
    assert result["orphans"][1]["name"] == "Whatsapp - Antigo"


@pytest.mark.asyncio
async def test_category_filter_passthrough(bound_context):
    """T2 cenário smoke: category filter passa ao GAQL builder."""
    from src.mcp.tools.audit_orphan_smart_actions import audit_orphan_smart_actions

    captured: dict = {}

    async def fake_run_report(*args, **kwargs):
        captured["query"] = kwargs.get("query", "")
        return []

    with patch(
        "src.mcp.tools.audit_orphan_smart_actions.run_report",
        AsyncMock(side_effect=fake_run_report),
    ):
        await audit_orphan_smart_actions({"customer_id": "1234567890", "category": "PURCHASE"})

    assert "conversion_action.category = 'PURCHASE'" in captured["query"]


@pytest.mark.asyncio
async def test_truncation_when_total_exceeds_limit(bound_context):
    """T4 cenário smoke: 50 orphans + limit=10 → truncated=true."""
    from src.mcp.tools.audit_orphan_smart_actions import audit_orphan_smart_actions

    fake_rows = [
        {
            "conversion_action_id": str(i),
            "name": f"ca_{i:03d}",
            "category": "CONTACT",
            "origin": "WEBSITE",
            "primary_for_goal": False,
            "status": "ENABLED",
            "all_conversions": 0.0,
        }
        for i in range(50)
    ]
    with patch(
        "src.mcp.tools.audit_orphan_smart_actions.run_report",
        AsyncMock(return_value=fake_rows),
    ):
        result = await audit_orphan_smart_actions({"customer_id": "1234567890", "limit": 10})

    assert result["total_orphans"] == 50
    assert result["truncated"] is True
    assert result["returned_count"] == 10
