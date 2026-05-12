"""Unit tests for the remove_audience MCP tool."""

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
        "customer_id": "1163862076",
        "target_type": "ad_group",
        "target_id": "183008426336",
        "criterion_ids": ["52988066042"],
    }


# Schema-level tests (5)


def test_schema_rejects_missing_target_type():
    from src.mcp.tools.remove_audience import _SCHEMA

    bad = _good_payload()
    del bad["target_type"]
    with pytest.raises(ValidationError):
        validate(bad, _SCHEMA)


def test_schema_rejects_invalid_target_type():
    from src.mcp.tools.remove_audience import _SCHEMA

    bad = _good_payload()
    bad["target_type"] = "removeall"
    with pytest.raises(ValidationError):
        validate(bad, _SCHEMA)


def test_schema_rejects_missing_target_id():
    from src.mcp.tools.remove_audience import _SCHEMA

    bad = _good_payload()
    del bad["target_id"]
    with pytest.raises(ValidationError):
        validate(bad, _SCHEMA)


def test_schema_rejects_empty_criterion_ids():
    from src.mcp.tools.remove_audience import _SCHEMA

    bad = _good_payload()
    bad["criterion_ids"] = []
    with pytest.raises(ValidationError):
        validate(bad, _SCHEMA)


def test_schema_rejects_over_100_criterion_ids():
    from src.mcp.tools.remove_audience import _SCHEMA

    bad = _good_payload()
    bad["criterion_ids"] = [str(i) for i in range(101)]
    with pytest.raises(ValidationError):
        validate(bad, _SCHEMA)


# Classification + flow tests (3)


@pytest.mark.asyncio
async def test_classify_always_confirms_count_one():
    """1 criterion → CONFIRM (always)."""
    from src.mcp.tools.remove_audience import remove_audience

    with (
        patch(
            "src.mcp.tools.remove_audience.create_pending",
            AsyncMock(return_value="TOKEN001"),
        ),
        patch("src.mcp.tools.remove_audience.connection") as conn_module,
    ):
        conn_module.get_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(
            return_value=AsyncMock()
        )
        conn_module.get_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(
            return_value=None
        )
        result = await remove_audience(_good_payload())

    assert result["status"] == "dry_run"
    assert result["confirmation_token"] == "TOKEN001"
    assert "sempre confirma" in result["confirmation_reason"].lower()


@pytest.mark.asyncio
async def test_classify_always_confirms_bulk():
    """50 criteria → still CONFIRM (no AUTO branch)."""
    from src.mcp.tools.remove_audience import remove_audience

    with (
        patch(
            "src.mcp.tools.remove_audience.create_pending",
            AsyncMock(return_value="TOKEN050"),
        ),
        patch("src.mcp.tools.remove_audience.connection") as conn_module,
    ):
        conn_module.get_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(
            return_value=AsyncMock()
        )
        conn_module.get_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(
            return_value=None
        )
        result = await remove_audience(
            {
                "customer_id": "1163862076",
                "target_type": "ad_group",
                "target_id": "183008426336",
                "criterion_ids": [str(100 + i) for i in range(50)],
            }
        )

    assert result["status"] == "dry_run"
    assert result["confirmation_token"] == "TOKEN050"


@pytest.mark.asyncio
async def test_confirm_path_payload_includes_partial_failure_flag():
    """Payload must include __partial_failure__: True so apply_change uses it."""
    from src.mcp.tools.remove_audience import remove_audience

    captured_payload: dict = {}

    async def fake_create_pending(*_args, **kwargs):
        captured_payload.update(kwargs["payload"])
        return "TOKEN_PF"

    with (
        patch(
            "src.mcp.tools.remove_audience.create_pending",
            AsyncMock(side_effect=fake_create_pending),
        ),
        patch("src.mcp.tools.remove_audience.connection") as conn_module,
    ):
        conn_module.get_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(
            return_value=AsyncMock()
        )
        conn_module.get_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(
            return_value=None
        )
        await remove_audience(_good_payload())

    assert captured_payload["__partial_failure__"] is True
    assert captured_payload["__target_count__"] == 1
    assert captured_payload["target_type"] == "ad_group"
    assert captured_payload["target_id"] == "183008426336"
    assert captured_payload["criterion_ids"] == ["52988066042"]


# Per-row mapping test (1)


def test_classify_partial_already_removed_mapping():
    """_classify_partial maps RESOURCE_NOT_FOUND family → 'already_removed'."""
    from src.mcp.tools.remove_audience import _classify_partial

    assert _classify_partial(None) == "removed"
    assert _classify_partial("RESOURCE_NOT_FOUND: criterion does not exist") == "already_removed"
    assert _classify_partial("Error: NOT_FOUND") == "already_removed"
    assert _classify_partial("CRITERION_NOT_FOUND") == "already_removed"
    assert _classify_partial("DOES_NOT_EXIST") == "already_removed"
    assert _classify_partial("Some other error") == "failed"
