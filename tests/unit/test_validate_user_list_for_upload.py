"""Unit tests for validate_user_list_for_upload helper (Sprint 3b.28)."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


@pytest.fixture
def fake_ctx():
    return {"manager_id": uuid4(), "session_id": uuid4(), "customer_id": "1163862076"}


def _make_row(
    user_list_id: str,
    list_type: str = "CRM_BASED_USER_LIST",
    read_only: bool = False,
    membership_status: str = "OPEN",
):
    return {
        "user_list": {
            "id": user_list_id,
            "name": f"Test list {user_list_id}",
            "type": list_type,
            "read_only": read_only,
            "membership_status": membership_status,
        }
    }


@pytest.mark.asyncio
async def test_user_list_exists_crm_based_enabled_returns_none(fake_ctx):
    from src.google_ads.queries._common import validate_user_list_for_upload

    rows = [_make_row("123")]
    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=rows),
    ):
        result = await validate_user_list_for_upload(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            user_list_id="123",
        )
    assert result is None


@pytest.mark.asyncio
async def test_missing_user_list_returns_error_with_id(fake_ctx):
    from src.google_ads.queries._common import validate_user_list_for_upload

    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=[]),
    ):
        result = await validate_user_list_for_upload(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            user_list_id="999",
        )
    assert result is not None
    assert "não existe" in result["error"]
    assert result["missing_id"] == "999"


@pytest.mark.asyncio
async def test_wrong_type_returns_error_with_type_name(fake_ctx):
    from src.google_ads.queries._common import validate_user_list_for_upload

    rows = [_make_row("123", list_type="LOGICAL_USER_LIST")]
    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=rows),
    ):
        result = await validate_user_list_for_upload(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            user_list_id="123",
        )
    assert result is not None
    assert "LOGICAL_USER_LIST" in result["error"]
    assert "CRM_BASED_USER_LIST" in result["error"]


@pytest.mark.asyncio
async def test_read_only_returns_error_mentioning_policy_acceptance(fake_ctx):
    from src.google_ads.queries._common import validate_user_list_for_upload

    rows = [_make_row("123", read_only=True)]
    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=rows),
    ):
        result = await validate_user_list_for_upload(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            user_list_id="123",
        )
    assert result is not None
    assert "read_only" in result["error"]
    assert "Customer Match" in result["error"]


@pytest.mark.asyncio
async def test_membership_status_closed_returns_error(fake_ctx):
    from src.google_ads.queries._common import validate_user_list_for_upload

    rows = [_make_row("123", membership_status="CLOSED")]
    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=rows),
    ):
        result = await validate_user_list_for_upload(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            user_list_id="123",
        )
    assert result is not None
    assert "CLOSED" in result["error"]
