"""Unit tests for get_recommendations row formatter."""

from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_get_recommendations_formatter_returns_minimal_shape() -> None:
    """Formatter shouldn't access removed impact metric fields."""
    from src.mcp.tools.get_recommendations import _row_formatter

    fake_row = MagicMock()
    fake_row.recommendation.resource_name = "customers/1234567890/recommendations/abc"
    fake_row.recommendation.type = "KEYWORD"

    result = _row_formatter(fake_row)

    assert result["resource_name"] == "customers/1234567890/recommendations/abc"
    assert result["type"] == "KEYWORD"
    assert result["type_pt"] == "Adicionar palavra-chave"
    # Should NOT have the deprecated metric keys:
    assert "current_clicks" not in result
    assert "potential_clicks" not in result
    assert "uplift_clicks" not in result


@pytest.mark.asyncio
async def test_get_recommendations_formatter_resolves_proto_intenum_to_name() -> None:
    """Real proto-plus IntEnum stringifies to the int ('29'); we must use .name."""
    from google.ads.googleads.v24.enums.types.recommendation_type import (
        RecommendationTypeEnum,
    )

    from src.mcp.tools.get_recommendations import _row_formatter

    sitelink_asset = RecommendationTypeEnum.RecommendationType(29)  # SITELINK_ASSET

    fake_row = MagicMock()
    fake_row.recommendation.resource_name = "customers/1234567890/recommendations/xyz"
    fake_row.recommendation.type = sitelink_asset

    result = _row_formatter(fake_row)

    # Regression: the prior formatter used str(rec.type).split('.')[-1] which
    # returned '29' for proto-plus IntEnum, breaking the PT-BR translation.
    assert result["type"] == "SITELINK_ASSET"
    assert result["type_pt"] == "Adicionar asset de sitelink"
