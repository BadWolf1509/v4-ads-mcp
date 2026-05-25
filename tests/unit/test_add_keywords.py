"""Unit tests for the add_keywords MCP tool."""

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
        "ad_group_id": "111",
        "keywords": [{"text": "nutricionista", "match_type": "EXACT"}],
    }


def test_schema_rejects_missing_text():
    from src.mcp.tools.add_keywords import _SCHEMA

    bad = _good_payload()
    bad["keywords"][0] = {"match_type": "EXACT"}  # missing text
    with pytest.raises(ValidationError):
        validate(bad, _SCHEMA)


def test_schema_rejects_oversized_text():
    from src.mcp.tools.add_keywords import _SCHEMA

    bad = _good_payload()
    bad["keywords"][0]["text"] = "x" * 81  # maxLength is 80
    with pytest.raises(ValidationError):
        validate(bad, _SCHEMA)


def test_schema_rejects_invalid_match_type():
    from src.mcp.tools.add_keywords import _SCHEMA

    bad = _good_payload()
    bad["keywords"][0]["match_type"] = "REGEX"
    with pytest.raises(ValidationError):
        validate(bad, _SCHEMA)


def test_schema_rejects_empty_keywords():
    from src.mcp.tools.add_keywords import _SCHEMA

    bad = _good_payload()
    bad["keywords"] = []
    with pytest.raises(ValidationError):
        validate(bad, _SCHEMA)


def test_schema_rejects_over_500_keywords():
    from src.mcp.tools.add_keywords import _SCHEMA

    bad = _good_payload()
    bad["keywords"] = [{"text": f"kw{i}", "match_type": "EXACT"} for i in range(501)]
    with pytest.raises(ValidationError):
        validate(bad, _SCHEMA)


def test_schema_accepts_optional_cpc_bid_micros():
    from src.mcp.tools.add_keywords import _SCHEMA

    payload = _good_payload()
    payload["keywords"][0]["cpc_bid_micros"] = 2000000
    validate(payload, _SCHEMA)  # must not raise


def test_schema_rejects_negative_cpc_bid():
    from src.mcp.tools.add_keywords import _SCHEMA

    bad = _good_payload()
    bad["keywords"][0]["cpc_bid_micros"] = 0
    with pytest.raises(ValidationError):
        validate(bad, _SCHEMA)


@pytest.mark.asyncio
async def test_auto_path_under_threshold():
    """5 KWs → AUTO, run_mutation called with partial_failure=True."""
    from src.mcp.tools.add_keywords import add_keywords

    captured = {}

    async def fake_run_mutation(**kwargs):
        captured.update(kwargs)
        return {
            "provider_request_id": "req-1",
            "applied_count": 5,
            "partial_failures": [{"index": i, "status": "added", "error": None} for i in range(5)],
        }

    with patch("src.mcp.tools.add_keywords.run_mutation", AsyncMock(side_effect=fake_run_mutation)):
        result = await add_keywords(
            {
                "customer_id": "1234567890",
                "ad_group_id": "111",
                "keywords": [{"text": f"kw {i}", "match_type": "EXACT"} for i in range(5)],
            }
        )

    assert result["status"] == "applied"
    assert result["applied_count"] == 5
    assert captured["partial_failure"] is True
    assert "confirmation_token" not in result


@pytest.mark.asyncio
async def test_confirm_path_over_threshold():
    """25 KWs → CONFIRM, create_pending called, token returned."""
    from src.mcp.tools.add_keywords import add_keywords

    with (
        patch("src.mcp.tools.add_keywords.create_pending", AsyncMock(return_value="ABC12345")),
        patch("src.mcp.tools.add_keywords.connection") as conn_module,
    ):
        conn_module.get_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(
            return_value=AsyncMock()
        )
        conn_module.get_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(
            return_value=None
        )
        result = await add_keywords(
            {
                "customer_id": "1234567890",
                "ad_group_id": "111",
                "keywords": [{"text": f"kw {i}", "match_type": "EXACT"} for i in range(25)],
            }
        )

    assert result["status"] == "dry_run"
    assert result["confirmation_token"] == "ABC12345"


@pytest.mark.asyncio
async def test_partial_failure_mapping_already_exists():
    """CRITERION_EXISTS partial_failure → row status='already_exists'."""
    from src.mcp.tools.add_keywords import add_keywords

    fake_partials = [
        {"index": 0, "status": "added", "error": None},
        {"index": 1, "status": "failed", "error": "CRITERION_EXISTS: keyword already exists"},
        {"index": 2, "status": "added", "error": None},
    ]
    with patch(
        "src.mcp.tools.add_keywords.run_mutation",
        AsyncMock(
            return_value={
                "provider_request_id": "req-2",
                "applied_count": 2,
                "partial_failures": fake_partials,
            }
        ),
    ):
        result = await add_keywords(
            {
                "customer_id": "1234567890",
                "ad_group_id": "111",
                "keywords": [
                    {"text": "a", "match_type": "EXACT"},
                    {"text": "b", "match_type": "EXACT"},
                    {"text": "c", "match_type": "EXACT"},
                ],
            }
        )

    assert result["added"][0]["status"] == "added"
    assert result["added"][1]["status"] == "already_exists"
    assert result["added"][2]["status"] == "added"


@pytest.mark.asyncio
async def test_custom_params_summary_aggregates_metadata():
    """Audit params_summary has match_types_distribution + with_custom_bid_count, no raw texts."""
    from src.mcp.tools.add_keywords import add_keywords

    captured = {}

    async def fake_run_mutation(**kwargs):
        captured.update(kwargs)
        return {
            "provider_request_id": "req-3",
            "applied_count": 4,
            "partial_failures": [{"index": i, "status": "added", "error": None} for i in range(4)],
        }

    with patch("src.mcp.tools.add_keywords.run_mutation", AsyncMock(side_effect=fake_run_mutation)):
        await add_keywords(
            {
                "customer_id": "1234567890",
                "ad_group_id": "111",
                "keywords": [
                    {"text": "a", "match_type": "EXACT", "cpc_bid_micros": 2000000},
                    {"text": "b", "match_type": "EXACT"},
                    {"text": "c", "match_type": "PHRASE", "cpc_bid_micros": 1500000},
                    {"text": "d", "match_type": "BROAD"},
                ],
            }
        )

    summary = captured["params_summary"]
    assert summary["ad_group_id"] == "111"
    assert summary["match_types_distribution"] == {"EXACT": 2, "PHRASE": 1, "BROAD": 1}
    assert summary["with_custom_bid_count"] == 2
    # Critical: keyword text fields are not surfaced into summary keys/values.
    # Text values would appear quoted in the dict's repr — confirm absence:
    serialized = str(summary)
    for raw_text in ("a", "b", "c", "d"):
        assert f"'{raw_text}'" not in serialized
