"""Unit tests for get_my_audit_log (Sprint 3b.13)."""

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


def _fake_event(
    operation: str,
    customer_id: str | None = None,
    action_type: str = "mutate",
) -> dict:
    return {
        "id": 1,
        "occurred_at": "2026-05-12T22:35:00+00:00",
        "operation": operation,
        "customer_id": customer_id,
        "action_type": action_type,
        "target_count": 1,
        "status": "success",
        "duration_ms": 100,
        "google_request_id": "req-abc",
        "error_message": None,
    }


@pytest.mark.asyncio
async def test_returns_events_with_default_params(_ctx) -> None:
    """No filters → returns last 7 days events for the manager."""
    from src.mcp.tools.get_my_audit_log import get_my_audit_log

    fake_events = [
        _fake_event("update_keyword_bid", "7862230676"),
        _fake_event("apply_audience", "7862230676"),
    ]

    with (
        patch(
            "src.mcp.tools.get_my_audit_log.audit_log.list_for_manager",
            AsyncMock(return_value=fake_events),
        ),
        patch(
            "src.mcp.tools.get_my_audit_log.audit_log.record",
            AsyncMock(),
        ),
        patch(
            "src.mcp.tools.get_my_audit_log.connection.get_pool",
        ) as mock_pool,
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        result = await get_my_audit_log({})

    assert result["count"] == 2
    assert len(result["events"]) == 2
    assert result["filters"]["days"] == 7
    assert result["filters"]["action_type"] == "all"
    assert result["filters"]["customer_id"] is None


@pytest.mark.asyncio
async def test_filter_by_customer_id(_ctx) -> None:
    """customer_id filter passed through to repo function."""
    from src.mcp.tools.get_my_audit_log import get_my_audit_log

    mock_list = AsyncMock(return_value=[_fake_event("update_keyword_bid", "7862230676")])
    with (
        patch("src.mcp.tools.get_my_audit_log.audit_log.list_for_manager", mock_list),
        patch("src.mcp.tools.get_my_audit_log.audit_log.record", AsyncMock()),
        patch("src.mcp.tools.get_my_audit_log.connection.get_pool") as mock_pool,
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        result = await get_my_audit_log({"customer_id": "7862230676"})

    call_kwargs = mock_list.call_args.kwargs
    assert call_kwargs["customer_id"] == "7862230676"
    assert result["filters"]["customer_id"] == "7862230676"


@pytest.mark.asyncio
async def test_filter_by_action_type_mutate(_ctx) -> None:
    """action_type='mutate' filter passed through."""
    from src.mcp.tools.get_my_audit_log import get_my_audit_log

    mock_list = AsyncMock(return_value=[_fake_event("update_keyword_bid", "7862230676", "mutate")])
    with (
        patch("src.mcp.tools.get_my_audit_log.audit_log.list_for_manager", mock_list),
        patch("src.mcp.tools.get_my_audit_log.audit_log.record", AsyncMock()),
        patch("src.mcp.tools.get_my_audit_log.connection.get_pool") as mock_pool,
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        result = await get_my_audit_log({"action_type": "mutate"})

    call_kwargs = mock_list.call_args.kwargs
    assert call_kwargs["action_type"] == "mutate"
    assert result["filters"]["action_type"] == "mutate"


@pytest.mark.asyncio
async def test_empty_result_when_no_events(_ctx) -> None:
    """Fresh manager with zero audit events returns count=0, events=[]."""
    from src.mcp.tools.get_my_audit_log import get_my_audit_log

    with (
        patch(
            "src.mcp.tools.get_my_audit_log.audit_log.list_for_manager",
            AsyncMock(return_value=[]),
        ),
        patch("src.mcp.tools.get_my_audit_log.audit_log.record", AsyncMock()),
        patch("src.mcp.tools.get_my_audit_log.connection.get_pool") as mock_pool,
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        result = await get_my_audit_log({})

    assert result["count"] == 0
    assert result["events"] == []
