"""Unit tests for apply_change tool (Sprint 3b.15 F13 — resource_names propagation)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
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
async def test_apply_change_propagates_resource_names(_ctx) -> None:
    """F13: resource_names from run_mutation flows through apply_change response."""
    from src.mcp.tools.apply_change import apply_change

    # Simulate a saved pending mutation returned by consume()
    fake_saved = MagicMock()
    fake_saved.operation_type = "create_ad_group"
    fake_saved.customer_id = "1234567890"
    fake_saved.blast_summary = "Criar 2 ad_group(s) em 1 campaign(s)."
    fake_saved.payload = {
        "ad_groups": [{"campaign_id": "100", "name": "AG1"}, {"campaign_id": "100", "name": "AG2"}],
        "__target_count__": 2,
    }

    # run_mutation now returns resource_names in its dict (F13)
    fake_mutation_result = {
        "google_request_id": "req-apply-test",
        "applied_count": 2,
        "partial_failures": [],
        "resource_names": [
            "customers/1234567890/adGroups/111",
            "customers/1234567890/adGroups/222",
        ],
    }

    from src.mcp.tools import apply_change as apply_change_module

    with (
        patch.object(apply_change_module, "connection") as mock_conn,
        patch("src.mcp.tools.apply_change.consume", AsyncMock(return_value=fake_saved)),
        patch(
            "src.mcp.tools.apply_change.run_mutation", AsyncMock(return_value=fake_mutation_result)
        ),
    ):
        mock_pool = MagicMock()
        mock_conn.get_pool.return_value = mock_pool
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await apply_change({"confirmation_token": "ABCD1234"})

    assert result["status"] == "applied"
    assert result["applied_count"] == 2
    assert result["google_request_id"] == "req-apply-test"
    assert "resource_names" in result
    assert result["resource_names"] == [
        "customers/1234567890/adGroups/111",
        "customers/1234567890/adGroups/222",
    ]
