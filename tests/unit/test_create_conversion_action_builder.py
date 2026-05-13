"""Unit tests for build_create_conversion_action (Sprint 3b.19A)."""

from __future__ import annotations

from src.google_ads.mutates.conversion_actions import build_create_conversion_action
from tests.unit.fixtures.proto_capture import make_capture_client


def _sample_action(**overrides):
    base = {"name": "Lead Test", "category": "LEAD", "type": "WEBPAGE"}
    base.update(overrides)
    return base


def test_builder_sets_name_category_type() -> None:
    """name + category + type set correctly on conversion_action."""
    client = make_capture_client()
    ops = build_create_conversion_action(
        client,
        "1234567890",
        {"conversion_actions": [_sample_action()]},
    )
    assert len(ops) == 1
    op = ops[0]
    assert op.field("conversion_action_operation.create.name") == "Lead Test"
    assert op.field("conversion_action_operation.create.category") == "CAT_LEAD"
    assert op.field("conversion_action_operation.create.type_") == "TYPE_WEBPAGE"


def test_builder_sets_status_enabled_default() -> None:
    """status always ENABLED on create (V4 invariant — diferente de create_ad_group/create_rsa)."""
    client = make_capture_client()
    ops = build_create_conversion_action(
        client,
        "1234567890",
        {"conversion_actions": [_sample_action()]},
    )
    op = ops[0]
    assert op.field("conversion_action_operation.create.status") == "STATUS_ENABLED"


def test_builder_sets_counting_type_default_when_omitted() -> None:
    """counting_type defaults to ONE_PER_CLICK if not provided."""
    client = make_capture_client()
    ops = build_create_conversion_action(
        client,
        "1234567890",
        {"conversion_actions": [_sample_action()]},
    )
    op = ops[0]
    assert op.field("conversion_action_operation.create.counting_type") == "COUNTING_ONE_PER_CLICK"


def test_builder_sets_counting_type_many_per_click_when_provided() -> None:
    """counting_type MANY_PER_CLICK passed through correctly."""
    client = make_capture_client()
    ops = build_create_conversion_action(
        client,
        "1234567890",
        {"conversion_actions": [_sample_action(counting_type="MANY_PER_CLICK")]},
    )
    op = ops[0]
    assert op.field("conversion_action_operation.create.counting_type") == "COUNTING_MANY_PER_CLICK"


def test_builder_value_settings_with_brl_hardcode() -> None:
    """value_settings provided → currency_code='BRL' (V4 invariant), default_value + always_use_default_value set."""
    client = make_capture_client()
    ops = build_create_conversion_action(
        client,
        "1234567890",
        {
            "conversion_actions": [
                _sample_action(
                    category="PURCHASE",
                    value_settings={
                        "default_value_brl": 250.0,
                        "always_use_default_value": True,
                    },
                )
            ]
        },
    )
    op = ops[0]
    assert (
        op.field("conversion_action_operation.create.value_settings.default_currency_code") == "BRL"
    )
    assert op.field("conversion_action_operation.create.value_settings.default_value") == 250.0
    assert (
        op.field("conversion_action_operation.create.value_settings.always_use_default_value")
        is True
    )


def test_builder_batch_of_3_mixed_categories() -> None:
    """Batch of 3 actions with different categories → 3 ops, each with distinct values."""
    client = make_capture_client()
    ops = build_create_conversion_action(
        client,
        "1234567890",
        {
            "conversion_actions": [
                _sample_action(name="A1", category="LEAD"),
                _sample_action(name="A2", category="PURCHASE", type="UPLOAD_CLICKS"),
                _sample_action(name="A3", category="SIGNUP", type="UPLOAD_CALLS"),
            ]
        },
    )
    assert len(ops) == 3
    assert ops[0].field("conversion_action_operation.create.name") == "A1"
    assert ops[0].field("conversion_action_operation.create.category") == "CAT_LEAD"
    assert ops[0].field("conversion_action_operation.create.type_") == "TYPE_WEBPAGE"
    assert ops[1].field("conversion_action_operation.create.name") == "A2"
    assert ops[1].field("conversion_action_operation.create.category") == "CAT_PURCHASE"
    assert ops[1].field("conversion_action_operation.create.type_") == "TYPE_UPLOAD_CLICKS"
    assert ops[2].field("conversion_action_operation.create.name") == "A3"
    assert ops[2].field("conversion_action_operation.create.category") == "CAT_SIGNUP"
    assert ops[2].field("conversion_action_operation.create.type_") == "TYPE_UPLOAD_CALLS"
