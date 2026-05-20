"""Unit tests for validate_conversion_actions_exist helper (Sprint 3b.27)."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


@pytest.fixture
def fake_ctx():
    return {"manager_id": uuid4(), "session_id": uuid4(), "customer_id": "1163862076"}


@pytest.mark.asyncio
async def test_all_actions_exist_and_enabled_returns_none(fake_ctx):
    from src.google_ads.queries._common import validate_conversion_actions_exist

    rows = [
        {"conversion_action": {"id": "123", "status": "ENABLED"}},
        {"conversion_action": {"id": "456", "status": "PAUSED"}},
    ]
    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=rows),
    ):
        result = await validate_conversion_actions_exist(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            conversion_action_ids=["123", "456"],
        )
    assert result is None


@pytest.mark.asyncio
async def test_missing_id_returns_missing_ids_dict(fake_ctx):
    from src.google_ads.queries._common import validate_conversion_actions_exist

    rows = [{"conversion_action": {"id": "123", "status": "ENABLED"}}]
    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=rows),
    ):
        result = await validate_conversion_actions_exist(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            conversion_action_ids=["123", "999"],
        )
    assert result is not None
    assert "missing_ids" in result
    assert result["missing_ids"] == ["999"]
    assert "não existe" in result["error"]


@pytest.mark.asyncio
async def test_removed_id_returns_removed_ids_dict(fake_ctx):
    from src.google_ads.queries._common import validate_conversion_actions_exist

    rows = [
        {"conversion_action": {"id": "123", "status": "ENABLED"}},
        {"conversion_action": {"id": "456", "status": "REMOVED"}},
    ]
    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=rows),
    ):
        result = await validate_conversion_actions_exist(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            conversion_action_ids=["123", "456"],
        )
    assert result is not None
    assert "removed_ids" in result
    assert result["removed_ids"] == ["456"]
    assert "REMOVED" in result["error"]


@pytest.mark.asyncio
async def test_missing_short_circuits_before_removed_check(fake_ctx):
    """If both missing and removed exist, missing takes priority (short-circuit)."""
    from src.google_ads.queries._common import validate_conversion_actions_exist

    rows = [{"conversion_action": {"id": "123", "status": "REMOVED"}}]
    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=rows),
    ):
        result = await validate_conversion_actions_exist(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            conversion_action_ids=["123", "999"],  # 999 missing, 123 removed
        )
    assert "missing_ids" in result
    assert "removed_ids" not in result  # short-circuit
