"""Integration tests for audit_goal_attribution (Sprint 3b.35)."""

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
async def test_panoramic_no_filter_composite_keys(bound_context):
    """T1 cenário smoke: sem category filter → composite keys."""
    from src.mcp.tools.audit_goal_attribution import audit_goal_attribution

    fake_actions = [
        {
            "id": "1",
            "name": "Whatsapp - JPA",
            "category": "CONTACT",
            "origin": "WEBSITE",
            "primary_for_goal": True,
            "include_in_conversions_metric": True,
            "status": "ENABLED",
        },
        {
            "id": "2",
            "name": "Compra Produto X",
            "category": "PURCHASE",
            "origin": "WEBSITE",
            "primary_for_goal": True,
            "include_in_conversions_metric": True,
            "status": "ENABLED",
        },
    ]
    fake_goals = [
        {"category": "CONTACT", "origin": "WEBSITE", "biddable": True},
        {"category": "PURCHASE", "origin": "WEBSITE", "biddable": True},
    ]

    async def fake_run_report(*args, **kwargs):
        op_name = kwargs.get("operation_name", "")
        if "actions" in op_name:
            return fake_actions
        return fake_goals

    with patch(
        "src.mcp.tools.audit_goal_attribution.run_report",
        AsyncMock(side_effect=fake_run_report),
    ):
        result = await audit_goal_attribution({"customer_id": "1234567890"})

    assert "CONTACT__WEBSITE" in result["origin_summary"]
    assert "PURCHASE__WEBSITE" in result["origin_summary"]
    assert result["total_actions_audited"] == 2
    assert result["category_filter"] is None


@pytest.mark.asyncio
async def test_category_filter_uses_origin_only_key(bound_context):
    """T2 cenário smoke: com category filter → key = origin simple."""
    from src.mcp.tools.audit_goal_attribution import audit_goal_attribution

    fake_actions = [
        {
            "id": "1",
            "name": "Whatsapp - JPA",
            "category": "CONTACT",
            "origin": "WEBSITE",
            "primary_for_goal": True,
            "include_in_conversions_metric": True,
            "status": "ENABLED",
        },
    ]
    fake_goals = [{"category": "CONTACT", "origin": "WEBSITE", "biddable": True}]

    async def fake_run_report(*args, **kwargs):
        op_name = kwargs.get("operation_name", "")
        if "actions" in op_name:
            return fake_actions
        return fake_goals

    with patch(
        "src.mcp.tools.audit_goal_attribution.run_report",
        AsyncMock(side_effect=fake_run_report),
    ):
        result = await audit_goal_attribution({"customer_id": "1234567890", "category": "CONTACT"})

    assert "WEBSITE" in result["origin_summary"]
    assert "CONTACT__WEBSITE" not in result["origin_summary"]
    assert result["category_filter"] == "CONTACT"


@pytest.mark.asyncio
async def test_warning_emitted_when_biddable_true(bound_context):
    """T4 cenário smoke: biddable=true → warning PT-BR emitido."""
    from src.mcp.tools.audit_goal_attribution import audit_goal_attribution

    fake_actions = [
        {
            "id": "1",
            "name": "Test Action",
            "category": "CONTACT",
            "origin": "WEBSITE",
            "primary_for_goal": True,
            "include_in_conversions_metric": True,
            "status": "ENABLED",
        },
    ]
    fake_goals = [{"category": "CONTACT", "origin": "WEBSITE", "biddable": True}]

    async def fake_run_report(*args, **kwargs):
        op_name = kwargs.get("operation_name", "")
        if "actions" in op_name:
            return fake_actions
        return fake_goals

    with patch(
        "src.mcp.tools.audit_goal_attribution.run_report",
        AsyncMock(side_effect=fake_run_report),
    ):
        result = await audit_goal_attribution({"customer_id": "1234567890", "category": "CONTACT"})

    summary = result["origin_summary"]["WEBSITE"]
    assert summary["biddable"] is True
    assert summary["warning"] is not None
    assert "AFETA Smart Bidding" in summary["warning"]
