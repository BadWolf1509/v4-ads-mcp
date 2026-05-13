"""Unit tests for update_rsa tool (Sprint 3b.18)."""

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


@pytest.mark.asyncio
async def test_returns_dry_run_with_token_on_happy_path(_ctx) -> None:
    """Pre-flight passes → CONFIRM dry_run with token."""
    from src.mcp.tools.update_rsa import update_rsa

    with (
        patch(
            "src.mcp.tools.update_rsa.validate_existing_rsas_for_update",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.mcp.tools.update_rsa.create_pending",
            AsyncMock(return_value="TOKEN1"),
        ),
        patch("src.mcp.tools.update_rsa.connection.get_pool") as mock_pool,
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        result = await update_rsa(
            {
                "customer_id": "1234567890",
                "updates": [{"ad_id": "100", "path1": "abc"}],
            }
        )

    assert result["status"] == "dry_run"
    assert result["confirmation_token"] == "TOKEN1"
    assert result["operation"] == "update_rsa"
    assert len(result["updates_preview"]) == 1
    assert "path1" in result["updates_preview"][0]["fields_updated"]


@pytest.mark.asyncio
async def test_returns_error_on_preflight_rejection(_ctx) -> None:
    """Pre-flight error → tool returns error response."""
    from src.mcp.tools.update_rsa import update_rsa

    with patch(
        "src.mcp.tools.update_rsa.validate_existing_rsas_for_update",
        AsyncMock(return_value="Ad 999 nao encontrado..."),
    ):
        result = await update_rsa(
            {
                "customer_id": "1234567890",
                "updates": [{"ad_id": "999", "path1": "abc"}],
            }
        )

    assert result["status"] == "error"
    assert "999 nao encontrado" in result["error"]
    assert result["operation"] == "update_rsa"


@pytest.mark.asyncio
async def test_builds_correct_blast_summary_for_mixed_batch(_ctx) -> None:
    """Mixed batch (different fields per update) → summary reflects distribution."""
    from src.mcp.tools.update_rsa import update_rsa

    with (
        patch(
            "src.mcp.tools.update_rsa.validate_existing_rsas_for_update",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.mcp.tools.update_rsa.create_pending",
            AsyncMock(return_value="TOKEN"),
        ),
        patch("src.mcp.tools.update_rsa.connection.get_pool") as mock_pool,
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        result = await update_rsa(
            {
                "customer_id": "1234567890",
                "updates": [
                    {"ad_id": "100", "headlines": ["H1", "H2", "H3"]},
                    {"ad_id": "101", "path1": "abc"},
                    {"ad_id": "102", "final_urls": ["https://example.com/"]},
                ],
            }
        )

    assert "3 RSA(s)" in result["blast_summary"]
    assert "headlines(1)" in result["blast_summary"]
    assert "path1(1)" in result["blast_summary"]
    assert "final_urls(1)" in result["blast_summary"]
