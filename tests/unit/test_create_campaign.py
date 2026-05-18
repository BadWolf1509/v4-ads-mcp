"""Unit tests for create_campaign tool (Sprint 3b.24): schema, runtime validation, pre-flight."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import jsonschema
import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current


@pytest.fixture(autouse=True)
def _ctx():
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _valid_payload(**overrides):
    """Build a valid minimal payload, with optional overrides."""
    base = {
        "customer_id": "1234567890",
        "name": "[3b.24 smoke test] T1",
        "bidding_strategy": {"type": "MAXIMIZE_CONVERSIONS"},
        "daily_budget_brl": 10.0,
        "geo_targets": ["geoTargetConstants/2076"],
    }
    base.update(overrides)
    return base


# ---------- Schema validation ----------


def test_schema_requires_core_fields():
    from src.mcp.tools.create_campaign import _SCHEMA

    # Missing customer_id
    invalid = {k: v for k, v in _valid_payload().items() if k != "customer_id"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, _SCHEMA)

    # Missing name
    invalid = {k: v for k, v in _valid_payload().items() if k != "name"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, _SCHEMA)

    # Missing bidding_strategy
    invalid = {k: v for k, v in _valid_payload().items() if k != "bidding_strategy"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, _SCHEMA)

    # Missing daily_budget_brl
    invalid = {k: v for k, v in _valid_payload().items() if k != "daily_budget_brl"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, _SCHEMA)

    # Missing geo_targets
    invalid = {k: v for k, v in _valid_payload().items() if k != "geo_targets"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, _SCHEMA)


def test_schema_rejects_additional_properties():
    from src.mcp.tools.create_campaign import _SCHEMA

    # advertising_channel_type is hardcoded internally, NOT in schema
    invalid = _valid_payload(advertising_channel_type="SEARCH")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, _SCHEMA)

    # status is hardcoded PAUSED, NOT in schema
    invalid = _valid_payload(status="ENABLED")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, _SCHEMA)


def test_schema_rejects_unknown_bidding_strategy():
    from src.mcp.tools.create_campaign import _SCHEMA

    invalid = _valid_payload(bidding_strategy={"type": "PORTFOLIO_TARGET_CPA"})
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, _SCHEMA)


def test_schema_accepts_all_6_bidding_strategies():
    from src.mcp.tools.create_campaign import _SCHEMA

    for strategy in [
        "MAXIMIZE_CONVERSIONS",
        "MAXIMIZE_CONVERSION_VALUE",
        "TARGET_CPA",
        "TARGET_ROAS",
        "MANUAL_CPC",
        "MAXIMIZE_CLICKS",
    ]:
        # Build minimal-valid per strategy
        bs = {"type": strategy}
        if strategy == "TARGET_CPA":
            bs["target_cpa_brl"] = 25.0
        elif strategy == "TARGET_ROAS":
            bs["target_roas"] = 4.0
        payload = _valid_payload(bidding_strategy=bs)
        # Should NOT raise
        jsonschema.validate(payload, _SCHEMA)


# ---------- Runtime _validate_payload_shape ----------


def test_runtime_target_cpa_requires_target_cpa_brl():
    from src.mcp.tools.create_campaign import _validate_payload_shape

    payload = _valid_payload(bidding_strategy={"type": "TARGET_CPA"})
    error = _validate_payload_shape(payload)
    assert error is not None
    assert "TARGET_CPA" in error
    assert "target_cpa_brl" in error


def test_runtime_target_roas_requires_target_roas():
    from src.mcp.tools.create_campaign import _validate_payload_shape

    payload = _valid_payload(bidding_strategy={"type": "TARGET_ROAS"})
    error = _validate_payload_shape(payload)
    assert error is not None
    assert "TARGET_ROAS" in error
    assert "target_roas" in error


def test_schema_rejects_enhanced_cpc_field():
    """F35 (Sprint 3b.24.4): enhanced_cpc removed from schema (deprecated by Google,
    rejected on Campaign create). additionalProperties: false on bidding_strategy
    means any payload containing it is now invalid at schema level.
    """
    from src.mcp.tools.create_campaign import _SCHEMA

    invalid = _valid_payload(bidding_strategy={"type": "MANUAL_CPC", "enhanced_cpc": True})
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, _SCHEMA)


def test_runtime_cpc_bid_ceiling_only_with_maximize_clicks():
    from src.mcp.tools.create_campaign import _validate_payload_shape

    payload = _valid_payload(bidding_strategy={"type": "MANUAL_CPC", "cpc_bid_ceiling_brl": 1.5})
    error = _validate_payload_shape(payload)
    assert error is not None
    assert "cpc_bid_ceiling_brl" in error
    assert "MAXIMIZE_CLICKS" in error

    # MAX_CLICKS + ceiling is OK
    payload = _valid_payload(
        bidding_strategy={"type": "MAXIMIZE_CLICKS", "cpc_bid_ceiling_brl": 1.5}
    )
    assert _validate_payload_shape(payload) is None


def test_runtime_target_cpa_brl_invalid_with_wrong_strategy():
    from src.mcp.tools.create_campaign import _validate_payload_shape

    # TARGET_ROAS + target_cpa_brl is invalid
    payload = _valid_payload(
        bidding_strategy={"type": "TARGET_ROAS", "target_roas": 4.0, "target_cpa_brl": 50.0}
    )
    error = _validate_payload_shape(payload)
    assert error is not None
    assert "target_cpa_brl" in error


def test_runtime_target_roas_invalid_with_wrong_strategy():
    from src.mcp.tools.create_campaign import _validate_payload_shape

    # MAX_CONVERSIONS + target_roas is invalid
    payload = _valid_payload(bidding_strategy={"type": "MAXIMIZE_CONVERSIONS", "target_roas": 4.0})
    error = _validate_payload_shape(payload)
    assert error is not None
    assert "target_roas" in error


def test_runtime_max_conv_optional_target_cpa_brl_ok():
    from src.mcp.tools.create_campaign import _validate_payload_shape

    # MAX_CONVERSIONS + target_cpa_brl is eCPC mode — valid
    payload = _valid_payload(
        bidding_strategy={"type": "MAXIMIZE_CONVERSIONS", "target_cpa_brl": 30.0}
    )
    assert _validate_payload_shape(payload) is None


def test_runtime_max_conv_value_optional_target_roas_ok():
    from src.mcp.tools.create_campaign import _validate_payload_shape

    # MAX_CONVERSION_VALUE + target_roas is valid (target roi mode)
    payload = _valid_payload(
        bidding_strategy={"type": "MAXIMIZE_CONVERSION_VALUE", "target_roas": 3.5}
    )
    assert _validate_payload_shape(payload) is None


def test_runtime_inverted_dates_rejected():
    from src.mcp.tools.create_campaign import _validate_payload_shape

    payload = _valid_payload(start_date="2026-12-31", end_date="2026-05-01")
    error = _validate_payload_shape(payload)
    assert error is not None
    assert "start_date" in error
    assert "end_date" in error


def test_runtime_valid_payload_returns_none():
    from src.mcp.tools.create_campaign import _validate_payload_shape

    assert _validate_payload_shape(_valid_payload()) is None


# ---------- Pre-flight geo BR validation integration ----------


@pytest.mark.asyncio
async def test_pre_flight_geo_rejection_propagates():
    from src.mcp.tools.create_campaign import create_campaign

    with (
        patch(
            "src.mcp.tools.create_campaign.validate_geo_target_constants_br_only",
            AsyncMock(
                return_value="Geo target 'Canada' (geoTargetConstants/...) tem country_code 'CA', esperado 'BR'."
            ),
        ),
    ):
        result = await create_campaign(_valid_payload(geo_targets=["geoTargetConstants/2124"]))

    assert result["status"] == "error"
    assert "BR" in result["error"]
    assert result["operation"] == "create_campaign"
