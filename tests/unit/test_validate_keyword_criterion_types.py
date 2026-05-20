"""Unit tests for validate_keyword_criterion_types helper (Sprint 3b.27 — F43 fix)."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


@pytest.fixture
def fake_ctx():
    return {"manager_id": uuid4(), "session_id": uuid4(), "customer_id": "7862230676"}


def _make_row(ad_group_id: str, criterion_id: str, negative: bool, type_name: str = "KEYWORD"):
    """Build a dict matching the row_formatter output of the helper."""
    return {
        "ad_group_id": ad_group_id,
        "criterion_id": criterion_id,
        "negative": negative,
        "type": type_name,
    }


@pytest.mark.asyncio
async def test_all_positive_returns_none(fake_ctx):
    from src.google_ads.queries._common import validate_keyword_criterion_types

    rows = [_make_row("1", "11", False), _make_row("1", "12", False)]
    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=rows),
    ):
        result = await validate_keyword_criterion_types(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            keyword_pairs=[("1", "11"), ("1", "12")],
        )
    assert result is None


@pytest.mark.asyncio
async def test_all_negative_returns_blocked_list_with_empty_safe(fake_ctx):
    from src.google_ads.queries._common import validate_keyword_criterion_types

    rows = [_make_row("1", "11", True), _make_row("1", "12", True)]
    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=rows),
    ):
        result = await validate_keyword_criterion_types(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            keyword_pairs=[("1", "11"), ("1", "12")],
        )
    assert result is not None
    assert len(result["negative_ids_blocked"]) == 2
    assert result["positive_ids_safe"] == []
    assert "2/2" in result["error"]


@pytest.mark.asyncio
async def test_mixed_returns_split_response(fake_ctx):
    from src.google_ads.queries._common import validate_keyword_criterion_types

    rows = [
        _make_row("1", "11", False),
        _make_row("1", "12", True),
        _make_row("2", "21", False),
    ]
    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=rows),
    ):
        result = await validate_keyword_criterion_types(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            keyword_pairs=[("1", "11"), ("1", "12"), ("2", "21")],
        )
    assert result is not None
    assert len(result["negative_ids_blocked"]) == 1
    assert result["negative_ids_blocked"][0]["criterion_id"] == "12"
    assert len(result["positive_ids_safe"]) == 2
    assert "1/3" in result["error"]
    assert "to_retry_with" in result


@pytest.mark.asyncio
async def test_missing_id_returns_missing_dict_curto_circuit(fake_ctx):
    from src.google_ads.queries._common import validate_keyword_criterion_types

    rows = [_make_row("1", "11", False)]
    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=rows),
    ):
        result = await validate_keyword_criterion_types(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            keyword_pairs=[("1", "11"), ("1", "12")],
        )
    assert result is not None
    assert "missing_ids" in result
    assert result["missing_ids"][0]["criterion_id"] == "12"
    assert "negative_ids_blocked" not in result


@pytest.mark.asyncio
async def test_pt_br_messages(fake_ctx):
    from src.google_ads.queries._common import validate_keyword_criterion_types

    rows = [_make_row("1", "11", True)]
    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=rows),
    ):
        result = await validate_keyword_criterion_types(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            keyword_pairs=[("1", "11")],
        )
    assert "negative=true" in result["error"]
    assert "positive_ids_safe" in result["error"]
    assert "Google Ads UI" in result["error"]


@pytest.mark.asyncio
async def test_to_retry_with_includes_positive_ids(fake_ctx):
    from src.google_ads.queries._common import validate_keyword_criterion_types

    rows = [_make_row("1", "11", False), _make_row("1", "12", True)]
    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=rows),
    ):
        result = await validate_keyword_criterion_types(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            keyword_pairs=[("1", "11"), ("1", "12")],
        )
    assert "positive_ids_safe" in result["to_retry_with"]
    assert "update_keyword_status" in result["to_retry_with"]


@pytest.mark.asyncio
async def test_empty_input_returns_none_without_calling_run_report(fake_ctx):
    from src.google_ads.queries._common import validate_keyword_criterion_types

    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=[]),
    ) as mock_run:
        result = await validate_keyword_criterion_types(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            keyword_pairs=[],
        )
    assert result is None
    mock_run.assert_not_called()
