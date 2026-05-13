"""Unit tests for get_my_rate_limit_status (Sprint 3b.12)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.governance.rate_limit import Usage
from src.mcp.context import McpRequestContext, clear_current, set_current


@pytest.fixture
def _ctx():
    ctx = McpRequestContext(manager_id=uuid4(), session_id=uuid4())
    set_current(ctx)
    yield ctx
    clear_current()


@pytest.mark.asyncio
async def test_returns_zero_usage_when_no_calls_today(_ctx) -> None:
    """No rate_counters row → returns 0 used, limit unchanged, 0% pct."""
    from src.mcp.tools.get_my_rate_limit_status import get_my_rate_limit_status

    fake_usage = Usage(used=0, limit=15000, pct=0.0)

    with (
        patch(
            "src.mcp.tools.get_my_rate_limit_status.get_today_usage",
            AsyncMock(return_value=fake_usage),
        ),
        patch(
            "src.mcp.tools.get_my_rate_limit_status.connection.get_pool",
        ) as mock_pool,
        patch(
            "src.mcp.tools.get_my_rate_limit_status.audit_log.record",
            AsyncMock(),
        ),
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await get_my_rate_limit_status({})

    assert result["used"] == 0
    assert result["limit"] == 15000
    assert result["remaining"] == 15000
    assert result["pct"] == 0.0
    assert result["pct_display"] == "0.0%"
    assert result["warning_threshold_pct"] == 80
    assert "date_utc" in result
    assert "developer_token_id_hash" in result


@pytest.mark.asyncio
async def test_returns_partial_usage(_ctx) -> None:
    """1234 ops used → pct ~8.2%, formatted properly."""
    from src.mcp.tools.get_my_rate_limit_status import get_my_rate_limit_status

    fake_usage = Usage(used=1234, limit=15000, pct=1234 / 15000)

    with (
        patch(
            "src.mcp.tools.get_my_rate_limit_status.get_today_usage",
            AsyncMock(return_value=fake_usage),
        ),
        patch(
            "src.mcp.tools.get_my_rate_limit_status.connection.get_pool",
        ) as mock_pool,
        patch(
            "src.mcp.tools.get_my_rate_limit_status.audit_log.record",
            AsyncMock(),
        ),
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await get_my_rate_limit_status({})

    assert result["used"] == 1234
    assert result["remaining"] == 13766
    assert result["pct"] == round(1234 / 15000, 4)
    assert result["pct_display"] == "8.2%"


@pytest.mark.asyncio
async def test_returns_high_usage_near_warning(_ctx) -> None:
    """13000 ops used → pct 86.7%, above 80% warning threshold."""
    from src.mcp.tools.get_my_rate_limit_status import get_my_rate_limit_status

    fake_usage = Usage(used=13000, limit=15000, pct=13000 / 15000)

    with (
        patch(
            "src.mcp.tools.get_my_rate_limit_status.get_today_usage",
            AsyncMock(return_value=fake_usage),
        ),
        patch(
            "src.mcp.tools.get_my_rate_limit_status.connection.get_pool",
        ) as mock_pool,
        patch(
            "src.mcp.tools.get_my_rate_limit_status.audit_log.record",
            AsyncMock(),
        ),
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await get_my_rate_limit_status({})

    assert result["used"] == 13000
    assert result["remaining"] == 2000
    assert result["pct_display"] == "86.7%"
    assert result["warning_threshold_pct"] == 80
