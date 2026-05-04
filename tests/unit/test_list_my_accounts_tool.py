"""Unit test for the list_my_accounts tool.

Mocks the DB layer so we test the tool's logic (context binding,
result shape, audit recording) without spinning up Postgres.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.db.repositories.google_ads_accounts import GoogleAdsAccount
from src.mcp.context import McpRequestContext, clear_current, set_current
from src.mcp.tools.list_my_accounts import list_my_accounts


@pytest.fixture
def bound_context():
    ctx = McpRequestContext(manager_id=uuid4(), session_id=uuid4())
    set_current(ctx)
    yield ctx
    clear_current()


@pytest.mark.asyncio
async def test_returns_account_list_shape(bound_context):
    from datetime import UTC, datetime

    fake_account = GoogleAdsAccount(
        customer_id="1234567890",
        mcc_id="9999999999",
        descriptive_name="Cliente Alpha",
        currency_code="BRL",
        time_zone="America/Sao_Paulo",
        is_test_account=False,
        is_active=True,
        synced_at=datetime.now(UTC),
    )

    mock_pool = MagicMock()
    mock_conn_ctx = AsyncMock()
    mock_pool.acquire = MagicMock(return_value=mock_conn_ctx)
    mock_conn_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
    mock_conn_ctx.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("src.mcp.tools.list_my_accounts.connection.get_pool", return_value=mock_pool),
        patch(
            "src.mcp.tools.list_my_accounts.manager_account_access.list_accounts_for_manager",
            AsyncMock(return_value=[fake_account]),
        ),
        patch(
            "src.mcp.tools.list_my_accounts.audit_log.record",
            AsyncMock(return_value=42),
        ),
    ):
        result = await list_my_accounts({})

    assert len(result) == 1
    assert result[0]["customer_id"] == "1234567890"
    assert result[0]["descriptive_name"] == "Cliente Alpha"
    assert result[0]["currency_code"] == "BRL"
    assert result[0]["is_test_account"] is False


@pytest.mark.asyncio
async def test_empty_when_no_accounts(bound_context):
    mock_pool = MagicMock()
    mock_conn_ctx = AsyncMock()
    mock_pool.acquire = MagicMock(return_value=mock_conn_ctx)
    mock_conn_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
    mock_conn_ctx.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("src.mcp.tools.list_my_accounts.connection.get_pool", return_value=mock_pool),
        patch(
            "src.mcp.tools.list_my_accounts.manager_account_access.list_accounts_for_manager",
            AsyncMock(return_value=[]),
        ),
        patch(
            "src.mcp.tools.list_my_accounts.audit_log.record",
            AsyncMock(return_value=42),
        ),
    ):
        result = await list_my_accounts({})
    assert result == []


@pytest.mark.asyncio
async def test_raises_without_bound_context():
    """Calling tool without binding context (programmer error) raises."""
    clear_current()
    with pytest.raises(RuntimeError, match="No MCP request context"):
        await list_my_accounts({})
