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
    """mode=exclusion + bid_modifier present → error (semanticamente N/A).

    Uses ad_group target_type so A4 rule (campaign+exclusion+user_list) does not
    fire first — tests only the bid_modifier+exclusion incompatibility rule.
    """
    from src.mcp.tools.apply_audience import apply_audience

    result = await apply_audience(
        {
            "customer_id": "1234567890",
            "target_type": "ad_group",
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


@pytest.mark.asyncio
async def test_preflight_rejects_campaign_user_list_exclusion():
    """A4 regression: campaign-level exclusion of user_list is silently dropped by Google.

    Tool must reject the combo with PT-BR error directing to ad_group level.
    """
    from src.mcp.tools.apply_audience import apply_audience

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
    assert result["status"] == "error"
    assert "user_list" in result["error"].lower() or "customer match" in result["error"].lower()
    assert "ad_group" in result["error"].lower()


@pytest.mark.asyncio
async def test_preflight_allows_campaign_user_interest_exclusion():
    """Sanity: user_interest exclusion at campaign level continues to work after A4 fix.

    A4 only blocks user_list exclusion at campaign level — user_interest is fine.
    """
    from src.mcp.tools.apply_audience import apply_audience

    fake_run_report = AsyncMock(return_value=[{"id": "91501", "taxonomy_type": "IN_MARKET"}])
    with (
        patch("src.mcp.tools.apply_audience.run_report", fake_run_report),
        patch("src.mcp.tools.apply_audience.create_pending", AsyncMock(return_value="TOKEN123")),
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
                        "audience_type": "user_interest",
                        "audience_resource_name": "customers/1234567890/userInterests/91501",
                    }
                ],
            }
        )

    # Either dry_run (exclusion always confirms) or applied — but NOT error
    assert result["status"] != "error"


# ----- AUTO + CONFIRM path tests (2) -----


@pytest.mark.asyncio
async def test_auto_path_observation_under_threshold():
    """5 observations → AUTO, run_mutation called with partial_failure=True."""
    from src.mcp.tools.apply_audience import apply_audience

    captured = {}

    async def fake_run_mutation(**kwargs):
        captured.update(kwargs)
        return {
            "provider_request_id": "req-1",
            "applied_count": 5,
            "partial_failures": [{"index": i, "status": "added", "error": None} for i in range(5)],
        }

    fake_run_report = AsyncMock(
        return_value=[{"id": str(91500 + i), "taxonomy_type": "IN_MARKET"} for i in range(5)]
    )
    with (
        patch("src.mcp.tools.apply_audience.run_report", fake_run_report),
        patch(
            "src.mcp.tools.apply_audience.run_mutation", AsyncMock(side_effect=fake_run_mutation)
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
    """1 exclusion → CONFIRM (always confirm in exclusion mode, regardless of count).

    Uses user_interest at campaign level so A4 rule does not block — only
    user_list exclusion at campaign is rejected (A4). user_interest exclusion
    at campaign continues to work normally.
    """
    from src.mcp.tools.apply_audience import apply_audience

    fake_run_report = AsyncMock(return_value=[{"id": "91501", "taxonomy_type": "IN_MARKET"}])
    with (
        patch("src.mcp.tools.apply_audience.run_report", fake_run_report),
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
                        "audience_type": "user_interest",
                        "audience_resource_name": "customers/1234567890/userInterests/91501",
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
    fake_run_report = AsyncMock(
        return_value=[
            {"id": "91501", "taxonomy_type": "IN_MARKET"},
            {"id": "91502", "taxonomy_type": "IN_MARKET"},
        ]
    )
    with (
        patch("src.mcp.tools.apply_audience.run_report", fake_run_report),
        patch(
            "src.mcp.tools.apply_audience.run_mutation",
            AsyncMock(
                return_value={
                    "provider_request_id": "req-2",
                    "applied_count": 1,
                    "partial_failures": fake_partials,
                }
            ),
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
            "provider_request_id": "req-3",
            "applied_count": 4,
            "partial_failures": [{"index": i, "status": "added", "error": None} for i in range(4)],
        }

    fake_run_report = AsyncMock(
        return_value=[
            {"id": "BBB", "taxonomy_type": "IN_MARKET"},
            {"id": "CCC", "taxonomy_type": "IN_MARKET"},
            {"id": "DDD", "taxonomy_type": "AFFINITY"},
        ]
    )
    with (
        patch("src.mcp.tools.apply_audience.run_report", fake_run_report),
        patch(
            "src.mcp.tools.apply_audience.run_mutation", AsyncMock(side_effect=fake_run_mutation)
        ),
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


# ----- A3 taxonomy pre-flight tests (5) -----


@pytest.mark.asyncio
async def test_taxonomy_preflight_rejects_vertical_geo():
    """A3 regression: VERTICAL_GEO (Display Topics, IDs 1-79999) silently dropped by Google.

    Pre-flight GAQL lookup detects taxonomy and rejects before mutation.
    """
    from unittest.mock import AsyncMock, patch

    from src.mcp.tools.apply_audience import apply_audience

    fake_run_report = AsyncMock(return_value=[{"id": "7", "taxonomy_type": "VERTICAL_GEO"}])
    with patch("src.mcp.tools.apply_audience.run_report", fake_run_report):
        result = await apply_audience(
            {
                "customer_id": "1234567890",
                "target_type": "ad_group",
                "mode": "observation",
                "attachments": [
                    {
                        "target_id": "111",
                        "audience_type": "user_interest",
                        "audience_resource_name": "customers/1234567890/userInterests/7",
                    }
                ],
            }
        )

    assert result["status"] == "error"
    assert "VERTICAL_GEO" in result["error"] or "taxonomy" in result["error"].lower()
    assert "IN_MARKET" in result["error"] or "AFFINITY" in result["error"]


@pytest.mark.asyncio
async def test_taxonomy_preflight_allows_in_market():
    """Sanity: IN_MARKET taxonomy passes through pre-flight (and gets to dispatch)."""
    from unittest.mock import AsyncMock, patch

    from src.mcp.tools.apply_audience import apply_audience

    fake_run_report = AsyncMock(return_value=[{"id": "80001", "taxonomy_type": "IN_MARKET"}])
    fake_run_mutation = AsyncMock(
        return_value={
            "provider_request_id": "req-1",
            "applied_count": 1,
            "partial_failures": [{"index": 0, "status": "added", "error": None}],
        }
    )
    with (
        patch("src.mcp.tools.apply_audience.run_report", fake_run_report),
        patch("src.mcp.tools.apply_audience.run_mutation", fake_run_mutation),
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
                        "audience_resource_name": "customers/1234567890/userInterests/80001",
                    }
                ],
            }
        )

    assert result["status"] == "applied"


@pytest.mark.asyncio
async def test_taxonomy_preflight_allows_affinity():
    """Sanity: AFFINITY taxonomy passes through."""
    from unittest.mock import AsyncMock, patch

    from src.mcp.tools.apply_audience import apply_audience

    fake_run_report = AsyncMock(return_value=[{"id": "90100", "taxonomy_type": "AFFINITY"}])
    fake_run_mutation = AsyncMock(
        return_value={
            "provider_request_id": "req-2",
            "applied_count": 1,
            "partial_failures": [{"index": 0, "status": "added", "error": None}],
        }
    )
    with (
        patch("src.mcp.tools.apply_audience.run_report", fake_run_report),
        patch("src.mcp.tools.apply_audience.run_mutation", fake_run_mutation),
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
                        "audience_resource_name": "customers/1234567890/userInterests/90100",
                    }
                ],
            }
        )

    assert result["status"] == "applied"


@pytest.mark.asyncio
async def test_taxonomy_preflight_skipped_when_no_user_interest():
    """Perf: GAQL lookup NOT called when batch is pure user_list."""
    from unittest.mock import AsyncMock, patch

    from src.mcp.tools.apply_audience import apply_audience

    fake_run_report = AsyncMock()  # Should NOT be called
    fake_run_mutation = AsyncMock(
        return_value={
            "provider_request_id": "req-3",
            "applied_count": 1,
            "partial_failures": [{"index": 0, "status": "added", "error": None}],
        }
    )
    with (
        patch("src.mcp.tools.apply_audience.run_report", fake_run_report),
        patch("src.mcp.tools.apply_audience.run_mutation", fake_run_mutation),
    ):
        result = await apply_audience(
            {
                "customer_id": "1234567890",
                "target_type": "ad_group",
                "mode": "observation",
                "attachments": [
                    {
                        "target_id": "111",
                        "audience_type": "user_list",
                        "audience_resource_name": "customers/1234567890/userLists/123",
                    }
                ],
            }
        )

    assert result["status"] == "applied"
    fake_run_report.assert_not_called()  # Perf gate


@pytest.mark.asyncio
async def test_taxonomy_preflight_batch_lookup_single_read():
    """Perf: 3 user_interest attachments → 1 GAQL call (not 3)."""
    from unittest.mock import AsyncMock, patch

    from src.mcp.tools.apply_audience import apply_audience

    fake_run_report = AsyncMock(
        return_value=[
            {"id": "80001", "taxonomy_type": "IN_MARKET"},
            {"id": "80002", "taxonomy_type": "IN_MARKET"},
            {"id": "90100", "taxonomy_type": "AFFINITY"},
        ]
    )
    fake_run_mutation = AsyncMock(
        return_value={
            "provider_request_id": "req-4",
            "applied_count": 3,
            "partial_failures": [{"index": i, "status": "added", "error": None} for i in range(3)],
        }
    )
    with (
        patch("src.mcp.tools.apply_audience.run_report", fake_run_report),
        patch("src.mcp.tools.apply_audience.run_mutation", fake_run_mutation),
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
                        "audience_resource_name": f"customers/1234567890/userInterests/{i}",
                    }
                    for i in (80001, 80002, 90100)
                ],
            }
        )

    assert result["status"] == "applied"
    assert fake_run_report.call_count == 1  # Single batch lookup
