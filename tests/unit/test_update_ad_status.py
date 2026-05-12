"""Unit tests for the update_ad_status MCP tool."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from jsonschema import ValidationError, validate


@pytest.fixture(autouse=True)
def _ctx():
    from src.mcp.context import McpRequestContext, clear_current, set_current

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _good_payload():
    return {
        "customer_id": "1234567890",
        "ads": [{"ad_group_id": "111", "ad_id": "222"}],
        "new_status": "PAUSED",
    }


def test_schema_rejects_missing_ad_group_id():
    from src.mcp.tools.update_ad_status import _SCHEMA

    bad = _good_payload()
    bad["ads"][0] = {"ad_id": "222"}  # missing ad_group_id
    with pytest.raises(ValidationError):
        validate(bad, _SCHEMA)


def test_schema_rejects_invalid_new_status():
    from src.mcp.tools.update_ad_status import _SCHEMA

    bad = _good_payload()
    bad["new_status"] = "FOO"
    with pytest.raises(ValidationError):
        validate(bad, _SCHEMA)


@pytest.mark.asyncio
async def test_auto_path_paused_under_threshold():
    """3 ads + PAUSED → AUTO, run_mutation called, no token."""
    from src.mcp.tools.update_ad_status import update_ad_status

    with patch(
        "src.mcp.tools.update_ad_status.run_mutation",
        AsyncMock(
            return_value={
                "google_request_id": "req-1",
                "applied_count": 3,
                "partial_failures": [],
            }
        ),
    ):
        result = await update_ad_status(
            {
                "customer_id": "1234567890",
                "ads": [
                    {"ad_group_id": "111", "ad_id": "1"},
                    {"ad_group_id": "111", "ad_id": "2"},
                    {"ad_group_id": "222", "ad_id": "3"},
                ],
                "new_status": "PAUSED",
            }
        )

    assert result["status"] == "applied"
    assert result["applied_count"] == 3
    assert result["google_request_id"] == "req-1"
    assert "confirmation_token" not in result


@pytest.mark.asyncio
async def test_confirm_path_bulk_over_threshold():
    """10 ads + PAUSED → CONFIRM, create_pending called, token returned."""
    from src.mcp.tools.update_ad_status import update_ad_status

    with (
        patch("src.mcp.tools.update_ad_status.create_pending", AsyncMock(return_value="ABC12345")),
        patch("src.mcp.tools.update_ad_status.connection") as conn_module,
    ):
        conn_module.get_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(
            return_value=AsyncMock()
        )
        conn_module.get_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(
            return_value=None
        )
        result = await update_ad_status(
            {
                "customer_id": "1234567890",
                "ads": [{"ad_group_id": "111", "ad_id": str(i)} for i in range(10)],
                "new_status": "PAUSED",
            }
        )

    assert result["status"] == "dry_run"
    assert result["confirmation_token"] == "ABC12345"
    assert "to_apply" in result


@pytest.mark.asyncio
async def test_confirm_path_remove_even_with_one_ad():
    """1 ad + REMOVED → CONFIRM (REMOVED always confirms regardless of count)."""
    from src.mcp.tools.update_ad_status import update_ad_status

    with (
        patch("src.mcp.tools.update_ad_status.create_pending", AsyncMock(return_value="REM00001")),
        patch("src.mcp.tools.update_ad_status.connection") as conn_module,
    ):
        conn_module.get_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(
            return_value=AsyncMock()
        )
        conn_module.get_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(
            return_value=None
        )
        result = await update_ad_status(
            {
                "customer_id": "1234567890",
                "ads": [{"ad_group_id": "111", "ad_id": "222"}],
                "new_status": "REMOVED",
            }
        )

    assert result["status"] == "dry_run"
    assert result["confirmation_token"] == "REM00001"
