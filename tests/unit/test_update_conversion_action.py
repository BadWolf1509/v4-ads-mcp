"""Unit tests for update_conversion_action tool — schema + Layer 2 (Sprint 3b.27).

Integration tests (Layer 3 mocking, dispatcher routing) live em
tests/integration/test_update_conversion_action.py — Task A5.
"""

from src.mcp.tools.update_conversion_action import _validate_payload_shape


def test_validate_payload_shape_accepts_well_formed_input():
    args = {
        "customer_id": "1163862076",
        "updates": [
            {"conversion_action_id": "123", "name": "Novo"},
            {"conversion_action_id": "456", "primary_for_goal": False},
        ],
    }
    assert _validate_payload_shape(args) is None


def test_validate_payload_shape_rejects_item_without_mutable_field():
    args = {
        "customer_id": "1163862076",
        "updates": [{"conversion_action_id": "123"}],
    }
    err = _validate_payload_shape(args)
    assert err is not None
    assert "sem nenhum field mutável" in err
    assert "conversion_action_id=123" in err


def test_validate_payload_shape_rejects_duplicate_conversion_action_id():
    args = {
        "customer_id": "1163862076",
        "updates": [
            {"conversion_action_id": "123", "name": "A"},
            {"conversion_action_id": "456", "name": "B"},
            {"conversion_action_id": "123", "primary_for_goal": False},
        ],
    }
    err = _validate_payload_shape(args)
    assert err is not None
    assert "duplicados" in err
    assert "123" in err


def test_validate_payload_shape_rejects_multiple_problems_with_first():
    """When multiple items have no mutable, report the first to keep msg concise."""
    args = {
        "customer_id": "1163862076",
        "updates": [
            {"conversion_action_id": "123"},
            {"conversion_action_id": "456"},
        ],
    }
    err = _validate_payload_shape(args)
    assert err is not None
    assert "conversion_action_id=123" in err
