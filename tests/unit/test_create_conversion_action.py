"""Unit tests for create_conversion_action tool (Sprint 3b.19A)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current


@pytest.fixture
def _ctx():
    ctx = McpRequestContext(manager_id=uuid4(), session_id=uuid4())
    set_current(ctx)
    yield ctx
    clear_current()


@pytest.mark.asyncio
async def test_returns_dry_run_with_token_on_happy_path(_ctx) -> None:
    """Pre-flight passes → CONFIRM dry_run with token + preview."""
    from src.mcp.tools.create_conversion_action import create_conversion_action

    with (
        patch(
            "src.mcp.tools.create_conversion_action.validate_conversion_action_create",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.mcp.tools.create_conversion_action.create_pending",
            AsyncMock(return_value="TOKEN1"),
        ),
        patch("src.mcp.tools.create_conversion_action.connection.get_pool") as mock_pool,
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        result = await create_conversion_action(
            {
                "customer_id": "1234567890",
                "conversion_actions": [
                    {"name": "Lead Test", "category": "SUBMIT_LEAD_FORM", "type": "WEBPAGE"}
                ],
            }
        )

    assert result["status"] == "dry_run"
    assert result["confirmation_token"] == "TOKEN1"
    assert result["operation"] == "create_conversion_action"
    assert len(result["actions_preview"]) == 1
    preview = result["actions_preview"][0]
    assert preview["name"] == "Lead Test"
    assert preview["category"] == "SUBMIT_LEAD_FORM"
    assert preview["type"] == "WEBPAGE"


@pytest.mark.asyncio
async def test_returns_error_on_preflight_duplicate_name(_ctx) -> None:
    """Pre-flight rejects duplicate → tool returns error response without token."""
    from src.mcp.tools.create_conversion_action import create_conversion_action

    with patch(
        "src.mcp.tools.create_conversion_action.validate_conversion_action_create",
        AsyncMock(return_value="ConversionAction 'Lead Test' ja existe na conta."),
    ):
        result = await create_conversion_action(
            {
                "customer_id": "1234567890",
                "conversion_actions": [
                    {"name": "Lead Test", "category": "SUBMIT_LEAD_FORM", "type": "WEBPAGE"}
                ],
            }
        )

    assert result["status"] == "error"
    assert "ja existe" in result["error"]
    assert result["operation"] == "create_conversion_action"
    assert "confirmation_token" not in result


@pytest.mark.asyncio
async def test_blast_summary_format_single_action(_ctx) -> None:
    """blast_summary string follows pattern: 'Criar N conversion_action(s): categorias {...}, tipos {...}.'"""
    from src.mcp.tools.create_conversion_action import create_conversion_action

    with (
        patch(
            "src.mcp.tools.create_conversion_action.validate_conversion_action_create",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.mcp.tools.create_conversion_action.create_pending",
            AsyncMock(return_value="T"),
        ),
        patch("src.mcp.tools.create_conversion_action.connection.get_pool") as mock_pool,
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        result = await create_conversion_action(
            {
                "customer_id": "1234567890",
                "conversion_actions": [
                    {"name": "Lead Test", "category": "SUBMIT_LEAD_FORM", "type": "WEBPAGE"}
                ],
            }
        )

    assert "Criar 1 conversion_action(s)" in result["blast_summary"]
    assert "'SUBMIT_LEAD_FORM': 1" in result["blast_summary"]
    assert "'WEBPAGE': 1" in result["blast_summary"]


@pytest.mark.asyncio
async def test_batch_3_actions_summary_distribution(_ctx) -> None:
    """3 actions with mixed categories/types → distribution correct in summary."""
    from src.mcp.tools.create_conversion_action import create_conversion_action

    with (
        patch(
            "src.mcp.tools.create_conversion_action.validate_conversion_action_create",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.mcp.tools.create_conversion_action.create_pending",
            AsyncMock(return_value="T"),
        ),
        patch("src.mcp.tools.create_conversion_action.connection.get_pool") as mock_pool,
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        result = await create_conversion_action(
            {
                "customer_id": "1234567890",
                "conversion_actions": [
                    {"name": "L1", "category": "SUBMIT_LEAD_FORM", "type": "WEBPAGE"},
                    {"name": "L2", "category": "SUBMIT_LEAD_FORM", "type": "UPLOAD_CLICKS"},
                    {"name": "P1", "category": "PURCHASE", "type": "WEBPAGE"},
                    # NOTE: F17 fix — LEAD removed from v20 schema. Using SUBMIT_LEAD_FORM x2.
                ],
            }
        )

    assert "Criar 3 conversion_action(s)" in result["blast_summary"]
    # Counter dict str format: {'SUBMIT_LEAD_FORM': 2, 'PURCHASE': 1}
    assert "'SUBMIT_LEAD_FORM': 2" in result["blast_summary"]
    assert "'PURCHASE': 1" in result["blast_summary"]
    assert "'WEBPAGE': 2" in result["blast_summary"]
    assert "'UPLOAD_CLICKS': 1" in result["blast_summary"]


@pytest.mark.asyncio
async def test_preview_includes_value_settings_flag(_ctx) -> None:
    """Preview indicates whether value_settings was provided."""
    from src.mcp.tools.create_conversion_action import create_conversion_action

    with (
        patch(
            "src.mcp.tools.create_conversion_action.validate_conversion_action_create",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.mcp.tools.create_conversion_action.create_pending",
            AsyncMock(return_value="T"),
        ),
        patch("src.mcp.tools.create_conversion_action.connection.get_pool") as mock_pool,
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        result = await create_conversion_action(
            {
                "customer_id": "1234567890",
                "conversion_actions": [
                    {
                        "name": "P1",
                        "category": "PURCHASE",
                        "type": "WEBPAGE",
                        "value_settings": {
                            "default_value_brl": 100.0,
                            "always_use_default_value": True,
                        },
                    },
                    {"name": "L1", "category": "SUBMIT_LEAD_FORM", "type": "WEBPAGE"},
                ],
            }
        )

    previews = result["actions_preview"]
    assert previews[0]["has_value_settings"] is True
    assert previews[1]["has_value_settings"] is False
