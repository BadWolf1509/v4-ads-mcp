"""Unit tests for import_offline_conversions tool (Sprint 3b.26).

Covers schema validation + runtime _validate_payload_shape (5 checks).
Dispatcher tests (run_conversion_upload) live in test_run_conversion_upload.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jsonschema
import pytest

from src.mcp.tools.import_offline_conversions import (
    _SCHEMA,
    _validate_payload_shape,
)


def _valid_conversion(offset_minutes: int = -60):
    """Build a valid conversion entry. Default: 60 minutes ago (safe window)."""
    brt = timezone(timedelta(hours=-3))
    dt = datetime.now(brt) + timedelta(minutes=offset_minutes)
    return {
        "gclid": "Cj0KCQjwTEST_VALID_GCLID_001",
        "conversion_date_time": dt.strftime("%Y-%m-%d %H:%M:%S"),
        "conversion_value_brl": 100.0,
    }


def _valid_payload(conversions=None):
    return {
        "customer_id": "1234567890",
        "conversion_action_id": "987654321",
        "conversions": conversions if conversions is not None else [_valid_conversion()],
    }


# ============================================================================
# Schema tests (JSONSchema Layer 1)
# ============================================================================


def test_schema_rejects_missing_customer_id():
    payload = {"conversion_action_id": "987654321", "conversions": [_valid_conversion()]}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _SCHEMA)


def test_schema_rejects_missing_conversion_action_id():
    payload = {"customer_id": "1234567890", "conversions": [_valid_conversion()]}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _SCHEMA)


def test_schema_rejects_empty_conversions_array():
    payload = {"customer_id": "1234567890", "conversion_action_id": "987654321", "conversions": []}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _SCHEMA)


def test_schema_rejects_more_than_100_conversions():
    payload = _valid_payload(conversions=[_valid_conversion()] * 101)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _SCHEMA)


def test_schema_rejects_invalid_date_format():
    bad = _valid_conversion()
    bad["conversion_date_time"] = "2026-05-18T14:30:00Z"  # ISO with T separator, not allowed
    payload = _valid_payload(conversions=[bad])
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _SCHEMA)


def test_schema_accepts_minimal_valid_payload():
    # Should NOT raise
    jsonschema.validate(_valid_payload(), _SCHEMA)


# ============================================================================
# Runtime _validate_payload_shape tests (Layer 2)
# ============================================================================


def test_validate_accepts_minimal_valid_payload():
    assert _validate_payload_shape(_valid_payload()) is None


def test_validate_rejects_conversion_in_future():
    # 10 minutes in future (outside 5-min clock skew)
    bad = _valid_conversion(offset_minutes=10)
    error = _validate_payload_shape(_valid_payload(conversions=[bad]))
    assert error is not None
    assert "futuro" in error["error"].lower()


def test_validate_accepts_future_within_5min_clock_skew():
    # 2 minutes in future — within clock skew tolerance
    ok = _valid_conversion(offset_minutes=2)
    assert _validate_payload_shape(_valid_payload(conversions=[ok])) is None


def test_validate_rejects_conversion_older_than_90_days():
    # 95 days ago (beyond Google's 90-day click-to-conversion window)
    bad = _valid_conversion(offset_minutes=-(95 * 24 * 60))
    error = _validate_payload_shape(_valid_payload(conversions=[bad]))
    assert error is not None
    assert "90 dias" in error["error"]


def test_validate_rejects_duplicate_gclids_in_batch():
    c1 = _valid_conversion()
    c2 = _valid_conversion()
    c2["gclid"] = c1["gclid"]  # same gclid
    error = _validate_payload_shape(_valid_payload(conversions=[c1, c2]))
    assert error is not None
    assert "gclids duplicados" in error["error"].lower()


def test_validate_rejects_duplicate_order_ids_in_batch():
    c1 = _valid_conversion()
    c1["order_id"] = "crm-001"
    c2 = _valid_conversion()
    c2["gclid"] = "Cj0KCQjwTEST_DIFFERENT_GCLID_002"
    c2["order_id"] = "crm-001"  # duplicate order_id
    error = _validate_payload_shape(_valid_payload(conversions=[c1, c2]))
    assert error is not None
    assert "order_id duplicados" in error["error"].lower()


def test_validate_accepts_distinct_order_ids():
    c1 = _valid_conversion()
    c1["order_id"] = "crm-001"
    c2 = _valid_conversion()
    c2["gclid"] = "Cj0KCQjwTEST_DIFFERENT_GCLID_002"
    c2["order_id"] = "crm-002"
    assert _validate_payload_shape(_valid_payload(conversions=[c1, c2])) is None


def test_validate_error_contains_row_index():
    # Make 2nd conversion (idx=1) invalid (future) — should report conversions[1]
    c1 = _valid_conversion()
    c2 = _valid_conversion(offset_minutes=10)  # future
    error = _validate_payload_shape(_valid_payload(conversions=[c1, c2]))
    assert error is not None
    assert "conversions[1]" in error["error"]


def test_validate_accepts_exactly_5min_clock_skew():
    """Boundary: exactly 5 minutes in future is accepted (clock skew tolerance)."""
    ok = _valid_conversion(offset_minutes=5)
    assert _validate_payload_shape(_valid_payload(conversions=[ok])) is None


def test_validate_rejects_conversion_at_exactly_91_days_old():
    """Boundary: conversions older than 90 days rejected (Google's hard window)."""
    bad = _valid_conversion(offset_minutes=-(91 * 24 * 60))
    error = _validate_payload_shape(_valid_payload(conversions=[bad]))
    assert error is not None
    assert "90 dias" in error["error"]


# ============================================================================
# No-composition-keywords regression guard (Sprint 3b.19B.1 convention)
# ============================================================================


def test_schema_has_no_composition_keywords():
    """Anthropic API rejects oneOf/allOf/anyOf at any nesting level."""
    import json

    schema_json = json.dumps(_SCHEMA)
    assert '"oneOf"' not in schema_json
    assert '"allOf"' not in schema_json
    assert '"anyOf"' not in schema_json
