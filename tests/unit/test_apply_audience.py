"""Unit tests for the apply_audience MCP tool."""

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
        "target_type": "ad_group",
        "mode": "observation",
        "attachments": [
            {
                "target_id": "111",
                "audience_type": "user_list",
                "audience_resource_name": "customers/1234567890/userLists/9377822529",
            }
        ],
    }


# ----- Schema rejection tests (6) -----


def test_schema_rejects_missing_target_type():
    from src.mcp.tools.apply_audience import _SCHEMA

    bad = _good_payload()
    del bad["target_type"]
    with pytest.raises(ValidationError):
        validate(bad, _SCHEMA)


def test_schema_rejects_invalid_mode():
    from src.mcp.tools.apply_audience import _SCHEMA

    bad = _good_payload()
    bad["mode"] = "targeting"  # dropped from scope
    with pytest.raises(ValidationError):
        validate(bad, _SCHEMA)


def test_schema_rejects_empty_attachments():
    from src.mcp.tools.apply_audience import _SCHEMA

    bad = _good_payload()
    bad["attachments"] = []
    with pytest.raises(ValidationError):
        validate(bad, _SCHEMA)


def test_schema_rejects_over_100_attachments():
    from src.mcp.tools.apply_audience import _SCHEMA

    bad = _good_payload()
    bad["attachments"] = [
        {
            "target_id": "111",
            "audience_type": "user_list",
            "audience_resource_name": f"customers/1234567890/userLists/{i}",
        }
        for i in range(101)
    ]
    with pytest.raises(ValidationError):
        validate(bad, _SCHEMA)


def test_schema_rejects_bid_modifier_out_of_range():
    from src.mcp.tools.apply_audience import _SCHEMA

    bad = _good_payload()
    bad["attachments"][0]["bid_modifier"] = 15.0  # max is 10.0
    with pytest.raises(ValidationError):
        validate(bad, _SCHEMA)


def test_schema_rejects_malformed_audience_resource_name():
    from src.mcp.tools.apply_audience import _SCHEMA

    bad = _good_payload()
    bad["attachments"][0]["audience_resource_name"] = "not-a-resource-name"
    with pytest.raises(ValidationError):
        validate(bad, _SCHEMA)


# ----- Pre-flight validation tests (3) -----


@pytest.mark.asyncio
async def test_preflight_rejects_bid_modifier_with_exclusion():
    """mode=exclusion + bid_modifier present → error (semanticamente N/A)."""
    from src.mcp.tools.apply_audience import apply_audience

    result = await apply_audience(
        {
            "customer_id": "1234567890",
            "target_type": "campaign",
            "mode": "exclusion",
            "attachments": [
                {
                    "target_id": "111",
                    "audience_type": "user_list",
                    "audience_resource_name": "customers/1234567890/userLists/123",
                    "bid_modifier": 1.5,
                }
            ],
        }
    )
    assert result["status"] == "error"
    assert "bid_modifier" in result["error"].lower()
    assert "exclusion" in result["error"].lower()


@pytest.mark.asyncio
async def test_preflight_rejects_audience_type_resource_name_mismatch():
    """audience_type='user_list' but resource_name points to /userInterests/ → error."""
    from src.mcp.tools.apply_audience import apply_audience

    result = await apply_audience(
        {
            "customer_id": "1234567890",
            "target_type": "ad_group",
            "mode": "observation",
            "attachments": [
                {
                    "target_id": "111",
                    "audience_type": "user_list",
                    "audience_resource_name": "customers/1234567890/userInterests/91501",  # WRONG
                }
            ],
        }
    )
    assert result["status"] == "error"
    assert "incompativel" in result["error"].lower() or "userLists" in result["error"]


@pytest.mark.asyncio
async def test_preflight_rejects_cross_account_resource_name():
    """resource_name from a different customer_id → error (prevents quota waste + Google opaque error)."""
    from src.mcp.tools.apply_audience import apply_audience

    result = await apply_audience(
        {
            "customer_id": "1234567890",
            "target_type": "ad_group",
            "mode": "observation",
            "attachments": [
                {
                    "target_id": "111",
                    "audience_type": "user_list",
                    "audience_resource_name": "customers/9999999999/userLists/123",  # WRONG CID
                }
            ],
        }
    )
    assert result["status"] == "error"
    assert "outra conta" in result["error"].lower() or "9999999999" in result["error"]


# ----- AUTO + CONFIRM path tests (2) -----


@pytest.mark.asyncio
async def test_auto_path_observation_under_threshold():
    """5 observations → AUTO, run_mutation called with partial_failure=True."""
    from src.mcp.tools.apply_audience import apply_audience

    captured = {}

    async def fake_run_mutation(**kwargs):
        captured.update(kwargs)
        return {
            "google_request_id": "req-1",
            "applied_count": 5,
            "partial_failures": [{"index": i, "status": "added", "error": None} for i in range(5)],
        }

    with patch(
        "src.mcp.tools.apply_audience.run_mutation", AsyncMock(side_effect=fake_run_mutation)
    ):
        result = await apply_audience(
            {
                "customer_id": "1234567890",
                "target_type": "ad_group",
                "mode": "observation",
                "attachments": [
                    {
                        "target_id": "111",
                        "audience_type": "user_interest",
                        "audience_resource_name": f"customers/1234567890/userInterests/{91500 + i}",
                    }
                    for i in range(5)
                ],
            }
        )

    assert result["status"] == "applied"
    assert result["applied_count"] == 5
    assert captured["partial_failure"] is True
    assert "confirmation_token" not in result


@pytest.mark.asyncio
async def test_confirm_path_exclusion_count_one():
    """1 exclusion → CONFIRM (always confirm in exclusion mode, regardless of count)."""
    from src.mcp.tools.apply_audience import apply_audience

    with (
        patch("src.mcp.tools.apply_audience.create_pending", AsyncMock(return_value="ABC12345")),
        patch("src.mcp.tools.apply_audience.connection") as conn_module,
    ):
        conn_module.get_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(
            return_value=AsyncMock()
        )
        conn_module.get_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(
            return_value=None
        )
        result = await apply_audience(
            {
                "customer_id": "1234567890",
                "target_type": "campaign",
                "mode": "exclusion",
                "attachments": [
                    {
                        "target_id": "22169885957",
                        "audience_type": "user_list",
                        "audience_resource_name": "customers/1234567890/userLists/9377822529",
                    }
                ],
            }
        )

    assert result["status"] == "dry_run"
    assert result["confirmation_token"] == "ABC12345"
    assert "exclusion" in result["confirmation_reason"].lower()


# ----- Per-row status mapping (1) -----


@pytest.mark.asyncio
async def test_partial_failure_mapping_already_attached():
    """CRITERION_EXISTS partial_failure → row status='already_attached'."""
    from src.mcp.tools.apply_audience import apply_audience

    fake_partials = [
        {"index": 0, "status": "added", "error": None},
        {"index": 1, "status": "failed", "error": "CRITERION_EXISTS: criterion already exists"},
    ]
    with patch(
        "src.mcp.tools.apply_audience.run_mutation",
        AsyncMock(
            return_value={
                "google_request_id": "req-2",
                "applied_count": 1,
                "partial_failures": fake_partials,
            }
        ),
    ):
        result = await apply_audience(
            {
                "customer_id": "1234567890",
                "target_type": "ad_group",
                "mode": "observation",
                "attachments": [
                    {
                        "target_id": "111",
                        "audience_type": "user_interest",
                        "audience_resource_name": "customers/1234567890/userInterests/91501",
                    },
                    {
                        "target_id": "111",
                        "audience_type": "user_interest",
                        "audience_resource_name": "customers/1234567890/userInterests/91502",
                    },
                ],
            }
        )

    assert result["attachments_result"][0]["status"] == "attached"
    assert result["attachments_result"][1]["status"] == "already_attached"


# ----- Custom params_summary privacy (1) -----


@pytest.mark.asyncio
async def test_custom_params_summary_aggregates_without_raw_resource_names():
    """params_summary has aggregates only; raw resource_names NEVER appear."""
    from src.mcp.tools.apply_audience import apply_audience

    captured = {}

    async def fake_run_mutation(**kwargs):
        captured.update(kwargs)
        return {
            "google_request_id": "req-3",
            "applied_count": 4,
            "partial_failures": [{"index": i, "status": "added", "error": None} for i in range(4)],
        }

    with patch(
        "src.mcp.tools.apply_audience.run_mutation", AsyncMock(side_effect=fake_run_mutation)
    ):
        await apply_audience(
            {
                "customer_id": "1234567890",
                "target_type": "ad_group",
                "mode": "observation",
                "attachments": [
                    {
                        "target_id": "111",
                        "audience_type": "user_list",
                        "audience_resource_name": "customers/1234567890/userLists/AAA",
                        "bid_modifier": 1.5,
                    },
                    {
                        "target_id": "111",
                        "audience_type": "user_interest",
                        "audience_resource_name": "customers/1234567890/userInterests/BBB",
                    },
                    {
                        "target_id": "222",
                        "audience_type": "user_interest",
                        "audience_resource_name": "customers/1234567890/userInterests/CCC",
                    },
                    {
                        "target_id": "222",
                        "audience_type": "user_interest",
                        "audience_resource_name": "customers/1234567890/userInterests/DDD",
                    },
                ],
            }
        )

    summary = captured["params_summary"]
    assert summary["target_type"] == "ad_group"
    assert summary["mode"] == "observation"
    assert summary["audience_types_distribution"] == {"user_list": 1, "user_interest": 3}
    assert summary["with_bid_modifier_count"] == 1
    assert summary["unique_targets_count"] == 2
    # Critical: raw resource_name fragments NOT in summary
    serialized = str(summary)
    for fragment in ("AAA", "BBB", "CCC", "DDD"):
        assert fragment not in serialized
