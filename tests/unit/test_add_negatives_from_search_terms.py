"""Unit tests for the add_negatives_from_search_terms MCP tool."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from jsonschema import ValidationError, validate


@pytest.fixture(autouse=True)
def _ctx():
    """Set MCP request context so get_current() works in the tool body."""
    from src.mcp.context import McpRequestContext, clear_current, set_current

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _good_payload():
    return {
        "customer_id": "1234567890",
        "negatives": [
            {"search_term": "ruim", "match_type": "EXACT", "scope": "campaign", "scope_id": "111"},
        ],
    }


def test_schema_accepts_minimal_payload():
    from src.mcp.tools.add_negatives_from_search_terms import _SCHEMA

    validate(_good_payload(), _SCHEMA)


def test_schema_defaults_match_type_to_exact():
    """match_type is optional; default is EXACT per spec §3.2."""
    from src.mcp.tools.add_negatives_from_search_terms import _SCHEMA

    payload = {
        "customer_id": "1234567890",
        "negatives": [{"search_term": "x", "scope": "campaign", "scope_id": "1"}],
    }
    validate(payload, _SCHEMA)  # must not raise


def test_schema_rejects_invalid_scope():
    from src.mcp.tools.add_negatives_from_search_terms import _SCHEMA

    bad = _good_payload()
    bad["negatives"][0]["scope"] = "account"
    with pytest.raises(ValidationError):
        validate(bad, _SCHEMA)


def test_schema_rejects_invalid_match_type():
    from src.mcp.tools.add_negatives_from_search_terms import _SCHEMA

    bad = _good_payload()
    bad["negatives"][0]["match_type"] = "REGEX"
    with pytest.raises(ValidationError):
        validate(bad, _SCHEMA)


def test_schema_rejects_empty_list():
    from src.mcp.tools.add_negatives_from_search_terms import _SCHEMA

    bad = _good_payload()
    bad["negatives"] = []
    with pytest.raises(ValidationError):
        validate(bad, _SCHEMA)


def test_schema_rejects_over_500_items():
    from src.mcp.tools.add_negatives_from_search_terms import _SCHEMA

    bad = _good_payload()
    bad["negatives"] = [
        {"search_term": f"t{i}", "scope": "campaign", "scope_id": "1"} for i in range(501)
    ]
    with pytest.raises(ValidationError):
        validate(bad, _SCHEMA)


@pytest.mark.asyncio
async def test_tool_zips_partial_failures_back_to_input():
    """run_mutation returns partial_failures[idx] = status; tool maps to per-row."""
    from src.mcp.tools.add_negatives_from_search_terms import add_negatives_from_search_terms

    fake_partials = [
        {"index": 0, "status": "added", "error": None},
        {"index": 1, "status": "failed", "error": "CRITERION_EXISTS"},
        {"index": 2, "status": "added", "error": None},
    ]

    with patch(
        "src.mcp.tools.add_negatives_from_search_terms.run_mutation",
        AsyncMock(
            return_value={
                "provider_request_id": "req-123",
                "applied_count": 2,
                "partial_failures": fake_partials,
            }
        ),
    ):
        result = await add_negatives_from_search_terms(
            {
                "customer_id": "1234567890",
                "negatives": [
                    {
                        "search_term": "a",
                        "match_type": "EXACT",
                        "scope": "campaign",
                        "scope_id": "111",
                    },
                    {
                        "search_term": "b",
                        "match_type": "EXACT",
                        "scope": "campaign",
                        "scope_id": "111",
                    },
                    {
                        "search_term": "c",
                        "match_type": "EXACT",
                        "scope": "ad_group",
                        "scope_id": "222",
                    },
                ],
            }
        )

    assert result["status"] == "applied"
    assert result["applied_count"] == 2
    assert result["provider_request_id"] == "req-123"
    assert len(result["added"]) == 3
    assert result["added"][0]["search_term"] == "a"
    assert result["added"][0]["status"] == "added"
    # Item 1 maps to CRITERION_EXISTS -> already_exists (the tool translates this code)
    assert result["added"][1]["search_term"] == "b"
    assert result["added"][1]["status"] == "already_exists"
    assert result["added"][2]["status"] == "added"


@pytest.mark.asyncio
async def test_tool_passes_custom_params_summary_to_run_mutation():
    """Spec §3.5: audit log gets scopes_distribution + match_types_distribution + scope_ids_count."""
    from src.mcp.tools.add_negatives_from_search_terms import add_negatives_from_search_terms

    captured = {}

    async def _stub(**kwargs):
        captured.update(kwargs)
        return {
            "provider_request_id": "r",
            "applied_count": 2,
            "partial_failures": [
                {"index": 0, "status": "added", "error": None},
                {"index": 1, "status": "added", "error": None},
            ],
        }

    with patch(
        "src.mcp.tools.add_negatives_from_search_terms.run_mutation",
        AsyncMock(side_effect=_stub),
    ):
        await add_negatives_from_search_terms(
            {
                "customer_id": "1234567890",
                "negatives": [
                    {
                        "search_term": "a",
                        "match_type": "EXACT",
                        "scope": "campaign",
                        "scope_id": "111",
                    },
                    {
                        "search_term": "b",
                        "match_type": "PHRASE",
                        "scope": "ad_group",
                        "scope_id": "222",
                    },
                ],
            }
        )

    assert captured["partial_failure"] is True
    summary = captured["params_summary"]
    assert summary == {
        "scopes_distribution": {"campaign": 1, "ad_group": 1},
        "match_types_distribution": {"EXACT": 1, "PHRASE": 1},
        "scope_ids_count": 2,
    }
