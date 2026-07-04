"""Unit tests for create_ad_group tool (Sprint 3b.14)."""

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
    """Pre-flight passes → CONFIRM dry_run with token returned."""
    from src.mcp.tools.create_ad_group import create_ad_group

    with (
        patch(
            "src.mcp.tools.create_ad_group.validate_parent_campaigns_for_ad_group_create",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.mcp.tools.create_ad_group.create_pending",
            AsyncMock(return_value="TOKEN123"),
        ),
        patch(
            "src.mcp.tools.create_ad_group.connection.get_pool",
        ) as mock_pool,
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await create_ad_group(
            {
                "customer_id": "1234567890",
                "ad_groups": [
                    {"campaign_id": "100", "name": "Test AG"},
                ],
            }
        )

    assert result["status"] == "dry_run"
    assert result["confirmation_token"] == "TOKEN123"
    assert result["operation"] == "create_ad_group"
    assert len(result["ad_groups_preview"]) == 1
    assert result["ad_groups_preview"][0]["status"] == "PAUSED"
    assert result["ad_groups_preview"][0]["type"] == "SEARCH_STANDARD"


@pytest.mark.asyncio
async def test_returns_error_on_preflight_rejection(_ctx) -> None:
    """Pre-flight returns error string → tool returns {status: 'error', error: ...}."""
    from src.mcp.tools.create_ad_group import create_ad_group

    with patch(
        "src.mcp.tools.create_ad_group.validate_parent_campaigns_for_ad_group_create",
        AsyncMock(return_value="Campaign 100 nao encontrada na conta..."),
    ):
        result = await create_ad_group(
            {
                "customer_id": "1234567890",
                "ad_groups": [{"campaign_id": "100", "name": "AG"}],
            }
        )

    assert result["status"] == "error"
    assert "100 nao encontrada" in result["error_message"]
    assert result["operation"] == "create_ad_group"


@pytest.mark.asyncio
async def test_builds_correct_blast_summary_for_mixed_batch(_ctx) -> None:
    """Mixed batch (different types/statuses/campaigns) → summary reflects distribution."""
    from src.mcp.tools.create_ad_group import create_ad_group

    with (
        patch(
            "src.mcp.tools.create_ad_group.validate_parent_campaigns_for_ad_group_create",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.mcp.tools.create_ad_group.create_pending",
            AsyncMock(return_value="TOKEN"),
        ),
        patch(
            "src.mcp.tools.create_ad_group.connection.get_pool",
        ) as mock_pool,
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await create_ad_group(
            {
                "customer_id": "1234567890",
                "ad_groups": [
                    {"campaign_id": "100", "name": "S1", "type": "SEARCH_STANDARD"},
                    {
                        "campaign_id": "100",
                        "name": "S2",
                        "type": "SEARCH_STANDARD",
                        "status": "ENABLED",
                    },
                    {"campaign_id": "200", "name": "SH1", "type": "SHOPPING_PRODUCT_ADS"},
                ],
            }
        )

    assert "3 ad_group(s)" in result["blast_summary"]
    assert "2 campaign(s)" in result["blast_summary"]
    assert "SEARCH_STANDARD(2)" in result["blast_summary"]
    assert "SHOPPING_PRODUCT_ADS(1)" in result["blast_summary"]
    assert "PAUSED(2)" in result["blast_summary"]
    assert "ENABLED(1)" in result["blast_summary"]
