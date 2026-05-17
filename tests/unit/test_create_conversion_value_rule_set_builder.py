"""Unit tests for build_create_conversion_value_rule_set (Sprint 3b.19B)."""

from __future__ import annotations

from src.google_ads.mutates.conversion_value_rules import (
    build_create_conversion_value_rule_set,
)
from tests.unit.fixtures.proto_capture import make_capture_client


def _device_rule(device_types=("MOBILE",), op="ADD", value=10.0):
    return {
        "action": {"operation": op, "value": value},
        "condition_type": "DEVICE",
        "device_condition": {"device_types": list(device_types)},
    }


def _geo_rule(geo_paths=("geoTargetConstants/20114",), op="ADD", value=30.0, match="ANY"):
    return {
        "action": {"operation": op, "value": value},
        "condition_type": "GEO_LOCATION",
        "geo_condition": {
            "geo_target_constants": list(geo_paths),
            "geo_match_type": match,
        },
    }


def test_builder_single_device_rule_customer_attachment() -> None:
    """1 DEVICE rule + CUSTOMER attachment → 2 ops (rule + set)."""
    client = make_capture_client()
    ops = build_create_conversion_value_rule_set(
        client,
        "1234567890",
        {"attachment_type": "CUSTOMER", "rules": [_device_rule()]},
    )
    assert len(ops) == 2  # 1 rule + 1 set
    rule_op = ops[0]
    set_op = ops[1]

    # Rule op
    assert "conversionValueRules/-1" in rule_op.field(
        "conversion_value_rule_operation.create.resource_name"
    )
    assert rule_op.field("conversion_value_rule_operation.create.action.operation") == "OP_ADD"
    assert rule_op.field("conversion_value_rule_operation.create.action.value") == 10.0
    assert (
        rule_op.field_count("conversion_value_rule_operation.create.device_condition.device_types")
        == 1
    )
    assert rule_op.field("conversion_value_rule_operation.create.status") == "RULE_STATUS_ENABLED"

    # Set op references the temp path
    assert (
        set_op.field("conversion_value_rule_set_operation.create.attachment_type")
        == "ATTACH_CUSTOMER"
    )
    assert (
        set_op.field_count("conversion_value_rule_set_operation.create.conversion_value_rules") == 1
    )
    assert set_op.field("conversion_value_rule_set_operation.create.status") == "SET_STATUS_ENABLED"


def test_builder_geo_rule_appends_constants_and_match_type() -> None:
    """GEO rule → geo_target_constants list populated + geo_match_type set."""
    client = make_capture_client()
    ops = build_create_conversion_value_rule_set(
        client,
        "1234567890",
        {
            "attachment_type": "CUSTOMER",
            "rules": [_geo_rule(geo_paths=("geoTargetConstants/2076", "geoTargetConstants/20114"))],
        },
    )
    rule_op = ops[0]
    assert (
        rule_op.field_count(
            "conversion_value_rule_operation.create.geo_location_condition.geo_target_constants"
        )
        == 2
    )
    assert (
        rule_op.field(
            "conversion_value_rule_operation.create.geo_location_condition.geo_match_type"
        )
        == "MATCH_ANY"
    )


def test_builder_mixed_batch_3_rules() -> None:
    """3 rules with mixed condition types → 4 ops total (3 rules + 1 set).

    Sprint 3b.22 (post-F25 cleanup): NO_CONDITION removed from enum. Mixed
    batch now uses DEVICE + GEO + DEVICE (different operations) to exercise
    sequential temp resource naming + dimension inference.
    """
    client = make_capture_client()
    ops = build_create_conversion_value_rule_set(
        client,
        "1234567890",
        {
            "attachment_type": "CUSTOMER",
            "rules": [
                _device_rule(),
                _geo_rule(),
                _device_rule(device_types=("DESKTOP",), op="MULTIPLY", value=1.5),
            ],
        },
    )
    assert len(ops) == 4
    # Each rule has distinct temp resource name -1, -2, -3
    for i in range(3):
        assert f"conversionValueRules/-{i + 1}" in ops[i].field(
            "conversion_value_rule_operation.create.resource_name"
        )


def test_builder_campaign_attachment_sets_campaign_path() -> None:
    """attachment_type=CAMPAIGN → rs.campaign = full campaign path."""
    client = make_capture_client()
    ops = build_create_conversion_value_rule_set(
        client,
        "1234567890",
        {
            "attachment_type": "CAMPAIGN",
            "campaign_id": "99",
            "rules": [_device_rule()],
        },
    )
    set_op = ops[-1]  # Last op is the set
    assert (
        set_op.field("conversion_value_rule_set_operation.create.campaign")
        == "customers/1234567890/campaigns/99"
    )
    assert (
        set_op.field("conversion_value_rule_set_operation.create.attachment_type")
        == "ATTACH_CAMPAIGN"
    )


def test_builder_customer_attachment_no_campaign_set() -> None:
    """attachment_type=CUSTOMER → rs.campaign NOT set."""
    client = make_capture_client()
    ops = build_create_conversion_value_rule_set(
        client,
        "1234567890",
        {"attachment_type": "CUSTOMER", "rules": [_device_rule()]},
    )
    set_op = ops[-1]
    assert set_op.has("conversion_value_rule_set_operation.create.campaign") is False


def test_builder_dimensions_inferred_from_rule_conditions() -> None:
    """rs.dimensions auto-derived from unique rule condition types."""
    client = make_capture_client()
    ops = build_create_conversion_value_rule_set(
        client,
        "1234567890",
        {
            "attachment_type": "CUSTOMER",
            "rules": [_device_rule(), _device_rule(device_types=("DESKTOP",)), _geo_rule()],
        },
    )
    set_op = ops[-1]
    # 2 unique dimensions: DEVICE + GEO_LOCATION (DEVICE appears twice but unique)
    assert set_op.field_count("conversion_value_rule_set_operation.create.dimensions") == 2
