"""Unit tests for create_conversion_value_rule_set tool (Sprint 3b.19B)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current


@pytest.fixture
def _ctx():
    ctx = McpRequestContext(manager_id=uuid4(), session_id=uuid4())
    set_current(ctx)
    yield ctx
    clear_current()


def _device_rule(value=10.0):
    return {
        "action": {"operation": "ADD", "value": value},
        "condition_type": "DEVICE",
        "device_condition": {"device_types": ["MOBILE"]},
    }


def _geo_rule(value=30.0):
    return {
        "action": {"operation": "ADD", "value": value},
        "condition_type": "GEO_LOCATION",
        "geo_condition": {
            "geo_target_constants": ["geoTargetConstants/20114"],
            "geo_match_type": "ANY",
        },
    }


@pytest.mark.asyncio
async def test_dry_run_happy_path_customer_device(_ctx) -> None:
    """CUSTOMER attachment + DEVICE rule → dry_run with token."""
    from src.mcp.tools.create_conversion_value_rule_set import (
        create_conversion_value_rule_set,
    )

    with (
        patch(
            "src.mcp.tools.create_conversion_value_rule_set.validate_campaign_for_value_rule_set",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.mcp.tools.create_conversion_value_rule_set.validate_geo_target_constants_for_value_rule",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.mcp.tools.create_conversion_value_rule_set.create_pending",
            AsyncMock(return_value="TOKEN1"),
        ),
        patch("src.mcp.tools.create_conversion_value_rule_set.connection.get_pool") as mock_pool,
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await create_conversion_value_rule_set(
            {
                "customer_id": "1234567890",
                "attachment_type": "CUSTOMER",
                "rules": [_device_rule()],
            }
        )

    assert result["status"] == "dry_run"
    assert result["confirmation_token"] == "TOKEN1"
    assert result["operation"] == "create_conversion_value_rule_set"
    assert result["preview"]["attachment_type"] == "CUSTOMER"
    assert result["preview"]["rule_count"] == 1


@pytest.mark.asyncio
async def test_dry_run_happy_path_campaign_with_geo(_ctx) -> None:
    """CAMPAIGN + GEO rule → both pre-flights called, dry_run OK."""
    from src.mcp.tools.create_conversion_value_rule_set import (
        create_conversion_value_rule_set,
    )

    campaign_validator = AsyncMock(return_value=None)
    geo_validator = AsyncMock(return_value=None)

    with (
        patch(
            "src.mcp.tools.create_conversion_value_rule_set.validate_campaign_for_value_rule_set",
            campaign_validator,
        ),
        patch(
            "src.mcp.tools.create_conversion_value_rule_set.validate_geo_target_constants_for_value_rule",
            geo_validator,
        ),
        patch(
            "src.mcp.tools.create_conversion_value_rule_set.create_pending",
            AsyncMock(return_value="T"),
        ),
        patch("src.mcp.tools.create_conversion_value_rule_set.connection.get_pool") as mock_pool,
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await create_conversion_value_rule_set(
            {
                "customer_id": "1234567890",
                "attachment_type": "CAMPAIGN",
                "campaign_id": "99",
                "rules": [_geo_rule()],
            }
        )

    assert result["status"] == "dry_run"
    campaign_validator.assert_called_once()
    geo_validator.assert_called_once()


@pytest.mark.asyncio
async def test_preflight_rejects_invalid_campaign(_ctx) -> None:
    """Campaign pre-flight returns error → tool returns error, no token."""
    from src.mcp.tools.create_conversion_value_rule_set import (
        create_conversion_value_rule_set,
    )

    with patch(
        "src.mcp.tools.create_conversion_value_rule_set.validate_campaign_for_value_rule_set",
        AsyncMock(return_value="Campaign 999 nao encontrada na conta. Verifique o campaign_id."),
    ):
        result = await create_conversion_value_rule_set(
            {
                "customer_id": "1234567890",
                "attachment_type": "CAMPAIGN",
                "campaign_id": "999",
                "rules": [_device_rule()],
            }
        )

    assert result["status"] == "error"
    assert "999" in result["error"]
    assert "confirmation_token" not in result


@pytest.mark.asyncio
async def test_preflight_rejects_non_br_geo_target(_ctx) -> None:
    """Geo pre-flight returns error → tool returns error PT-BR."""
    from src.mcp.tools.create_conversion_value_rule_set import (
        create_conversion_value_rule_set,
    )

    with (
        patch(
            "src.mcp.tools.create_conversion_value_rule_set.validate_campaign_for_value_rule_set",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.mcp.tools.create_conversion_value_rule_set.validate_geo_target_constants_for_value_rule",
            AsyncMock(
                return_value=(
                    "Geo target 'United States' (geoTargetConstants/2840) tem "
                    "country_code 'US', esperado 'BR' (V4 invariant)."
                )
            ),
        ),
    ):
        result = await create_conversion_value_rule_set(
            {
                "customer_id": "1234567890",
                "attachment_type": "CUSTOMER",
                "rules": [_geo_rule()],
            }
        )

    assert result["status"] == "error"
    assert "country_code 'US'" in result["error"]
    assert "BR" in result["error"]


@pytest.mark.asyncio
async def test_blast_summary_format_mixed_batch(_ctx) -> None:
    """Mixed rules → summary string with attachment_type + counter distributions."""
    from src.mcp.tools.create_conversion_value_rule_set import (
        create_conversion_value_rule_set,
    )

    with (
        patch(
            "src.mcp.tools.create_conversion_value_rule_set.validate_campaign_for_value_rule_set",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.mcp.tools.create_conversion_value_rule_set.validate_geo_target_constants_for_value_rule",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.mcp.tools.create_conversion_value_rule_set.create_pending",
            AsyncMock(return_value="T"),
        ),
        patch("src.mcp.tools.create_conversion_value_rule_set.connection.get_pool") as mock_pool,
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await create_conversion_value_rule_set(
            {
                "customer_id": "1234567890",
                "attachment_type": "CUSTOMER",
                "rules": [_device_rule(), _geo_rule()],
            }
        )

    assert "RuleSet (CUSTOMER)" in result["blast_summary"]
    assert "2 rule(s)" in result["blast_summary"]
    assert "'ADD': 2" in result["blast_summary"]
    assert "'DEVICE': 1" in result["blast_summary"]
    assert "'GEO_LOCATION': 1" in result["blast_summary"]


@pytest.mark.asyncio
async def test_preview_includes_attachment_and_filter_flags(_ctx) -> None:
    """Preview structure includes attachment_type + rule_count + filter flag."""
    from src.mcp.tools.create_conversion_value_rule_set import (
        create_conversion_value_rule_set,
    )

    with (
        patch(
            "src.mcp.tools.create_conversion_value_rule_set.validate_campaign_for_value_rule_set",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.mcp.tools.create_conversion_value_rule_set.validate_geo_target_constants_for_value_rule",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.mcp.tools.create_conversion_value_rule_set.create_pending",
            AsyncMock(return_value="T"),
        ),
        patch("src.mcp.tools.create_conversion_value_rule_set.connection.get_pool") as mock_pool,
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await create_conversion_value_rule_set(
            {
                "customer_id": "1234567890",
                "attachment_type": "CAMPAIGN",
                "campaign_id": "99",
                "conversion_action_categories": ["PURCHASE"],
                "rules": [_device_rule()],
            }
        )

    preview = result["preview"]
    assert preview["attachment_type"] == "CAMPAIGN"
    assert preview["rule_count"] == 1
    assert preview["has_category_filter"] is True
    assert "ADD" in preview["operations"]
