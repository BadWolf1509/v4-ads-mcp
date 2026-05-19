"""Unit tests for import_offline_conversions tool (Sprint 3b.26).

Covers schema validation + runtime _validate_payload_shape (5 checks).
Dispatcher tests (run_conversion_upload) live in test_run_conversion_upload.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

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


# ============================================================================
# Dry-run flow tests (Layer 1 + Layer 2 + Layer 3 + audit prep)
# ============================================================================


@pytest.mark.asyncio
async def test_tool_returns_dry_run_with_token_and_summary():
    from src.mcp.context import McpRequestContext, clear_current, set_current
    from src.mcp.tools.import_offline_conversions import import_offline_conversions

    ctx = McpRequestContext(manager_id=uuid4(), session_id=uuid4())
    set_current(ctx)
    try:
        mock_conn = AsyncMock()
        mock_pool = MagicMock()
        mock_acquire_cm = MagicMock()
        mock_acquire_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire.return_value = mock_acquire_cm

        with (
            patch(
                "src.mcp.tools.import_offline_conversions.validate_conversion_action_for_upload",
                AsyncMock(return_value=None),
            ),
            patch(
                "src.mcp.tools.import_offline_conversions.create_pending",
                AsyncMock(return_value="TOKEN001"),
            ),
            patch(
                "src.mcp.tools.import_offline_conversions.connection.get_pool",
                return_value=mock_pool,
            ),
        ):
            args = _valid_payload()
            result = await import_offline_conversions(args)

        assert result["status"] == "dry_run"
        assert result["operation"] == "import_offline_conversions"
        assert result["confirmation_token"] == "TOKEN001"
        assert "summary" in result
        assert result["summary"]["conversion_count"] == 1
    finally:
        clear_current()


@pytest.mark.asyncio
async def test_tool_summary_includes_sum_value_and_date_range():
    from src.mcp.context import McpRequestContext, clear_current, set_current
    from src.mcp.tools.import_offline_conversions import import_offline_conversions

    ctx = McpRequestContext(manager_id=uuid4(), session_id=uuid4())
    set_current(ctx)
    try:
        mock_conn = AsyncMock()
        mock_pool = MagicMock()
        mock_acquire_cm = MagicMock()
        mock_acquire_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire.return_value = mock_acquire_cm

        c1 = _valid_conversion(offset_minutes=-1440)  # 1 day ago
        c1["conversion_value_brl"] = 100.0
        c2 = _valid_conversion(offset_minutes=-60)  # 1 hour ago
        c2["gclid"] = "Cj0_DIFFERENT"
        c2["conversion_value_brl"] = 250.0

        with (
            patch(
                "src.mcp.tools.import_offline_conversions.validate_conversion_action_for_upload",
                AsyncMock(return_value=None),
            ),
            patch(
                "src.mcp.tools.import_offline_conversions.create_pending",
                AsyncMock(return_value="TOKEN002"),
            ),
            patch(
                "src.mcp.tools.import_offline_conversions.connection.get_pool",
                return_value=mock_pool,
            ),
        ):
            args = _valid_payload(conversions=[c1, c2])
            result = await import_offline_conversions(args)

        summary = result["summary"]
        assert summary["conversion_count"] == 2
        assert summary["sum_value_brl"] == 350.0
        assert summary["gclids_distinct"] == 2
        assert summary["order_ids_present"] == 0
        assert "earliest" in summary["date_range"]
        assert "latest" in summary["date_range"]
    finally:
        clear_current()


@pytest.mark.asyncio
async def test_tool_summary_counts_order_ids_present():
    from src.mcp.context import McpRequestContext, clear_current, set_current
    from src.mcp.tools.import_offline_conversions import import_offline_conversions

    ctx = McpRequestContext(manager_id=uuid4(), session_id=uuid4())
    set_current(ctx)
    try:
        mock_conn = AsyncMock()
        mock_pool = MagicMock()
        mock_acquire_cm = MagicMock()
        mock_acquire_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire.return_value = mock_acquire_cm

        c1 = _valid_conversion()
        c1["order_id"] = "crm-001"
        c2 = _valid_conversion()
        c2["gclid"] = "Cj0_DIFFERENT_2"  # no order_id
        c3 = _valid_conversion()
        c3["gclid"] = "Cj0_DIFFERENT_3"
        c3["order_id"] = "crm-003"

        with (
            patch(
                "src.mcp.tools.import_offline_conversions.validate_conversion_action_for_upload",
                AsyncMock(return_value=None),
            ),
            patch(
                "src.mcp.tools.import_offline_conversions.create_pending",
                AsyncMock(return_value="TOKEN003"),
            ),
            patch(
                "src.mcp.tools.import_offline_conversions.connection.get_pool",
                return_value=mock_pool,
            ),
        ):
            args = _valid_payload(conversions=[c1, c2, c3])
            result = await import_offline_conversions(args)

        assert result["summary"]["order_ids_present"] == 2
    finally:
        clear_current()


@pytest.mark.asyncio
async def test_tool_pre_flight_error_propagates():
    from src.mcp.context import McpRequestContext, clear_current, set_current
    from src.mcp.tools.import_offline_conversions import import_offline_conversions

    ctx = McpRequestContext(manager_id=uuid4(), session_id=uuid4())
    set_current(ctx)
    try:
        with patch(
            "src.mcp.tools.import_offline_conversions.validate_conversion_action_for_upload",
            AsyncMock(return_value="conversion_action_id=999 não existe em customer_id=1234567890"),
        ):
            args = _valid_payload()
            args["conversion_action_id"] = "999"
            result = await import_offline_conversions(args)

        assert result["status"] == "error"
        assert "não existe" in result["error"]
        assert "confirmation_token" not in result
    finally:
        clear_current()
