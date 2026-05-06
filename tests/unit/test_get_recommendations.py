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
