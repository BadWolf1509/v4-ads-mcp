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
        "provider_request_id": "req-apply-test",
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
    assert result["provider_request_id"] == "req-apply-test"
    assert "resource_names" in result
    assert result["resource_names"] == [
        "customers/1234567890/adGroups/111",
        "customers/1234567890/adGroups/222",
    ]


# ---------------------------------------------------------------------------
# Sprint 3b.26 — dispatcher branching regression guards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_change_routes_import_offline_conversions_to_run_conversion_upload():
    """Sprint 3b.26: import_offline_conversions operation_type routes to
    run_conversion_upload (NOT run_mutation)."""
    from src.mcp.context import McpRequestContext, clear_current, set_current
    from src.mcp.tools.apply_change import apply_change

    session_id = uuid4()
    ctx = McpRequestContext(manager_id=uuid4(), session_id=session_id)
    set_current(ctx)
    try:
        saved_pending = MagicMock()
        saved_pending.operation_type = "import_offline_conversions"
        saved_pending.customer_id = "1234567890"
        saved_pending.blast_summary = "Importar 5 conversões offline"
        saved_pending.payload = {
            "conversion_action_id": "987654321",
            "conversions": [],
            "__target_count__": 5,
            "__params_summary__": {"conversion_count": 5},
        }

        mock_conn = AsyncMock()
        mock_pool = MagicMock()
        mock_acquire_cm = MagicMock()
        mock_acquire_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire.return_value = mock_acquire_cm

        with (
            patch(
                "src.mcp.tools.apply_change.consume",
                AsyncMock(return_value=saved_pending),
            ),
            patch(
                "src.mcp.tools.apply_change.connection.get_pool",
                return_value=mock_pool,
            ),
            patch(
                "src.mcp.tools.apply_change.run_conversion_upload",
                AsyncMock(
                    return_value={
                        "status": "applied",
                        "operation": "import_offline_conversions",
                        "customer_id": "1234567890",
                        "applied_count": 5,
                        "failed_count": 0,
                        "failures": [],
                        "provider_request_id": "req-conv-001",
                    }
                ),
            ) as mock_conv_upload,
            patch(
                "src.mcp.tools.apply_change.run_mutation",
                AsyncMock(return_value={"provider_request_id": "should-not-be-called"}),
            ) as mock_mutate,
        ):
            result = await apply_change({"confirmation_token": "TOKEN001"})

        # Verify run_conversion_upload was called, run_mutation was NOT
        assert mock_conv_upload.called
        assert not mock_mutate.called

        # Verify response includes import_offline_conversions-specific fields
        assert result["status"] == "applied"
        assert result["operation"] == "import_offline_conversions"
        assert result["applied_count"] == 5
        assert result["failed_count"] == 0
        assert result["failures"] == []
    finally:
        clear_current()


@pytest.mark.asyncio
async def test_apply_change_routes_other_operations_to_run_mutation():
    """Regression guard: non-import_offline_conversions operations still route
    to run_mutation."""
    from src.mcp.context import McpRequestContext, clear_current, set_current
    from src.mcp.tools.apply_change import apply_change

    session_id = uuid4()
    ctx = McpRequestContext(manager_id=uuid4(), session_id=session_id)
    set_current(ctx)
    try:
        saved_pending = MagicMock()
        saved_pending.operation_type = "create_campaign"  # NOT import_offline_conversions
        saved_pending.customer_id = "1234567890"
        saved_pending.blast_summary = "Criar 1 campanha"
        saved_pending.payload = {
            "__target_count__": 4,
        }

        mock_conn = AsyncMock()
        mock_pool = MagicMock()
        mock_acquire_cm = MagicMock()
        mock_acquire_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire.return_value = mock_acquire_cm

        with (
            patch(
                "src.mcp.tools.apply_change.consume",
                AsyncMock(return_value=saved_pending),
            ),
            patch(
                "src.mcp.tools.apply_change.connection.get_pool",
                return_value=mock_pool,
            ),
            patch(
                "src.mcp.tools.apply_change.run_conversion_upload",
                AsyncMock(return_value={"should-not-be-called": True}),
            ) as mock_conv_upload,
            patch(
                "src.mcp.tools.apply_change.run_mutation",
                AsyncMock(
                    return_value={
                        "provider_request_id": "req-mut-001",
                        "applied_count": 4,
                        "resource_names": ["customers/X/campaigns/Y"],
                    }
                ),
            ) as mock_mutate,
        ):
            result = await apply_change({"confirmation_token": "TOKEN002"})

        # Verify run_mutation was called, run_conversion_upload was NOT
        assert mock_mutate.called
        assert not mock_conv_upload.called
        assert result["status"] == "applied"
        assert result["operation"] == "create_campaign"
    finally:
        clear_current()
