"""Unit tests for create_and_link_assets tool (Sprint 3b.25).

Covers schema validation + runtime _validate_payload_shape.
Builder tests live in test_create_and_link_assets_builder.py (separate file).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import jsonschema
import pytest

from src.mcp.tools.create_and_link_assets import (
    _SCHEMA,
    _validate_payload_shape,
)


def _valid_sitelink_asset():
    return {
        "type": "SITELINK",
        "attachment_level": "CAMPAIGN",
        "attachment_id": "customers/1234567890/campaigns/99999",
        "link_text": "Sobre nós",
        "final_urls": ["https://example.com/sobre"],
    }


def _valid_payload(assets=None):
    return {
        "customer_id": "1234567890",
        "assets": assets if assets is not None else [_valid_sitelink_asset()],
    }


# ============================================================================
# Schema tests (JSONSchema layer — Layer 1)
# ============================================================================


def test_schema_rejects_missing_customer_id():
    payload = {"assets": [_valid_sitelink_asset()]}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _SCHEMA)


def test_schema_rejects_empty_assets_array():
    payload = {"customer_id": "1234567890", "assets": []}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _SCHEMA)


def test_schema_rejects_more_than_20_assets():
    payload = _valid_payload(assets=[_valid_sitelink_asset()] * 21)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _SCHEMA)


def test_schema_rejects_invalid_phone_number_with_letters():
    asset = {
        "type": "CALL",
        "attachment_level": "CAMPAIGN",
        "attachment_id": "customers/1234567890/campaigns/99999",
        "phone_number": "abc-not-a-number",
    }
    payload = _valid_payload(assets=[asset])
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


def test_validate_rejects_sitelink_with_callout_text():
    asset = _valid_sitelink_asset()
    asset["callout_text"] = "Atendimento 24h"
    error = _validate_payload_shape(_valid_payload(assets=[asset]))
    assert error is not None
    assert "callout_text" in error["error_message"]
    assert error["operation"] == "create_and_link_assets"


def test_validate_rejects_promotion_with_both_discounts():
    asset = {
        "type": "PROMOTION",
        "attachment_level": "CAMPAIGN",
        "attachment_id": "customers/1234567890/campaigns/99999",
        "promotion_target": "Verão 2026",
        "discount_modifier": "UP_TO",
        "percent_off": 20.0,
        "money_amount_off_brl": 50.0,
        "final_urls": ["https://example.com/promo"],
    }
    error = _validate_payload_shape(_valid_payload(assets=[asset]))
    assert error is not None
    assert "exatamente um" in error["error_message"].lower()


def test_validate_rejects_promotion_without_any_discount():
    asset = {
        "type": "PROMOTION",
        "attachment_level": "CAMPAIGN",
        "attachment_id": "customers/1234567890/campaigns/99999",
        "promotion_target": "Verão 2026",
        "discount_modifier": "UP_TO",
        "final_urls": ["https://example.com/promo"],
    }
    error = _validate_payload_shape(_valid_payload(assets=[asset]))
    assert error is not None
    assert "exatamente um" in error["error_message"].lower()


def test_validate_rejects_sitelink_with_only_description1():
    asset = _valid_sitelink_asset()
    asset["description1"] = "Apenas linha 1"
    # Missing description2
    error = _validate_payload_shape(_valid_payload(assets=[asset]))
    assert error is not None
    assert "ambos" in error["error_message"].lower()


def test_validate_rejects_customer_level_with_non_matching_id():
    asset = _valid_sitelink_asset()
    asset["attachment_level"] = "CUSTOMER"
    asset["attachment_id"] = "9999999999"  # different customer
    error = _validate_payload_shape(_valid_payload(assets=[asset]))
    assert error is not None
    assert "customer_id" in error["error_message"]


def test_validate_rejects_campaign_level_with_invalid_resource_path():
    asset = _valid_sitelink_asset()
    asset["attachment_id"] = "99999"  # raw id, not resource path
    error = _validate_payload_shape(_valid_payload(assets=[asset]))
    assert error is not None
    assert (
        "resource path" in error["error_message"].lower() or "customers/" in error["error_message"]
    )


def test_validate_rejects_ad_group_level_with_invalid_resource_path():
    asset = _valid_sitelink_asset()
    asset["attachment_level"] = "AD_GROUP"
    asset["attachment_id"] = "77777"  # raw id, not resource path
    error = _validate_payload_shape(_valid_payload(assets=[asset]))
    assert error is not None
    assert "adGroups" in error["error_message"] or "resource path" in error["error_message"].lower()


def test_validate_rejects_promotion_end_date_before_start():
    asset = {
        "type": "PROMOTION",
        "attachment_level": "CAMPAIGN",
        "attachment_id": "customers/1234567890/campaigns/99999",
        "promotion_target": "Verão 2026",
        "discount_modifier": "UP_TO",
        "percent_off": 20.0,
        "final_urls": ["https://example.com/promo"],
        "start_date": "2026-06-01",
        "end_date": "2026-05-01",
    }
    error = _validate_payload_shape(_valid_payload(assets=[asset]))
    assert error is not None
    assert "end_date" in error["error_message"]
    assert "start_date" in error["error_message"]


def test_validate_error_contains_asset_index():
    """Errors must identify which asset in the list failed."""
    bad_asset = _valid_sitelink_asset()
    bad_asset["callout_text"] = "wrong"
    payload = _valid_payload(assets=[_valid_sitelink_asset(), bad_asset])
    error = _validate_payload_shape(payload)
    assert error is not None
    assert "assets[1]" in error["error_message"]


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
# Dry-run flow tests (Layer 1 + Layer 2 + audit prep)
# ============================================================================


@pytest.mark.asyncio
async def test_tool_returns_dry_run_with_token_and_summary():
    from src.mcp.context import McpRequestContext, clear_current, set_current
    from src.mcp.tools.create_and_link_assets import create_and_link_assets

    ctx = McpRequestContext(manager_id=uuid4(), session_id=uuid4())
    set_current(ctx)
    try:
        # Mock pool.acquire context manager + create_pending
        mock_conn = AsyncMock()
        mock_pool = MagicMock()
        mock_acquire_cm = MagicMock()
        mock_acquire_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire.return_value = mock_acquire_cm

        with (
            patch(
                "src.mcp.tools.create_and_link_assets.create_pending",
                AsyncMock(return_value="test-token-123"),
            ),
            patch(
                "src.mcp.tools.create_and_link_assets.connection.get_pool",
                return_value=mock_pool,
            ),
        ):
            args = {
                "customer_id": "1234567890",
                "assets": [_valid_sitelink_asset()],
            }
            result = await create_and_link_assets(args)

        assert result["status"] == "dry_run"
        assert result["operation"] == "create_and_link_assets"
        assert result["confirmation_token"] == "test-token-123"
        assert "summary" in result
    finally:
        clear_current()


@pytest.mark.asyncio
async def test_tool_summary_includes_counts_by_type_and_level():
    from src.mcp.context import McpRequestContext, clear_current, set_current
    from src.mcp.tools.create_and_link_assets import create_and_link_assets

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
                "src.mcp.tools.create_and_link_assets.create_pending",
                AsyncMock(return_value="test-token-456"),
            ),
            patch(
                "src.mcp.tools.create_and_link_assets.connection.get_pool",
                return_value=mock_pool,
            ),
        ):
            callout_customer = {
                "type": "CALLOUT",
                "attachment_level": "CUSTOMER",
                "attachment_id": "1234567890",
                "callout_text": "Atendimento 24h",
            }
            args = {
                "customer_id": "1234567890",
                "assets": [
                    _valid_sitelink_asset(),
                    _valid_sitelink_asset(),
                    callout_customer,
                ],
            }
            result = await create_and_link_assets(args)

        summary = result["summary"]
        assert summary["asset_count"] == 3
        assert summary["by_type"] == {"SITELINK": 2, "CALLOUT": 1}
        assert summary["by_level"] == {"CAMPAIGN": 2, "CUSTOMER": 1}
        assert summary["total_ops_chained"] == 6
    finally:
        clear_current()


# ============================================================================
# _build_summary direct unit test (pure function, no mocks needed)
# ============================================================================


def test_build_summary_returns_correct_counts_and_distinct_ids():
    """_build_summary computes counts + distinct attachment_ids correctly.

    Tests deduplication branch: 2 SITELINKs share same campaign attachment_id,
    so attachment_ids_distinct == 1 (not 2).
    """
    from src.mcp.tools.create_and_link_assets import _build_summary

    payload = {
        "customer_id": "1234567890",
        "assets": [
            {
                "type": "SITELINK",
                "attachment_level": "CAMPAIGN",
                "attachment_id": "customers/1234567890/campaigns/99999",
                "link_text": "Sobre",
                "final_urls": ["https://example.com/sobre"],
            },
            {
                "type": "SITELINK",
                "attachment_level": "CAMPAIGN",
                "attachment_id": "customers/1234567890/campaigns/99999",  # same campaign
                "link_text": "Contato",
                "final_urls": ["https://example.com/contato"],
            },
            {
                "type": "CALLOUT",
                "attachment_level": "CUSTOMER",
                "attachment_id": "1234567890",
                "callout_text": "Atendimento 24h",
            },
        ],
    }

    summary = _build_summary(payload)

    assert summary == {
        "asset_count": 3,
        "by_type": {"SITELINK": 2, "CALLOUT": 1},
        "by_level": {"CAMPAIGN": 2, "CUSTOMER": 1},
        "attachment_ids_distinct": 2,  # 1 campaign + 1 customer = 2 distinct
        "total_ops_chained": 6,
    }
