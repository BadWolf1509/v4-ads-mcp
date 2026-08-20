"""Unit tests for get_my_rate_limit_status (Sprint 3b.12).

Estes tres cobrem a ARITMETICA e a formatacao do bloco `account`. O mock
devolve o mesmo Usage pras duas chaves, entao nao expressam a diferenca
entre os dois niveis — isso e o que test_rate_limit_status_manager_cap.py
faz, com side_effect por chave.
"""

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

    conta = result["account"]
    assert conta["used"] == 0
    assert conta["limit"] == 15000
    assert conta["remaining"] == 15000
    assert conta["pct"] == 0.0
    assert conta["pct_display"] == "0.0%"
    assert result["warning_threshold_pct"] == 80
    assert "date_utc" in result
    assert "developer_token_id_hash" in conta


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

    conta = result["account"]
    assert conta["used"] == 1234
    assert conta["remaining"] == 13766
    assert conta["pct"] == round(1234 / 15000, 4)
    assert conta["pct_display"] == "8.2%"


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

    conta = result["account"]
    assert conta["used"] == 13000
    assert conta["remaining"] == 2000
    assert conta["pct_display"] == "86.7%"
    assert result["warning_threshold_pct"] == 80
