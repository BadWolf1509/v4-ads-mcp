"""Unit tests for create_rsa tool (Sprint 3b.16)."""

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


def _sample_rsa(**overrides):
    base = {
        "ad_group_id": "100",
        "headlines": ["H1", "H2", "H3", "H4", "H5"],
        "descriptions": ["Desc one longer text", "Desc two another"],
        "final_urls": ["https://example.com/"],
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_returns_dry_run_with_token_on_happy_path(_ctx) -> None:
    """Pre-flight passes → CONFIRM dry_run with token."""
    from src.mcp.tools.create_rsa import create_rsa

    with (
        patch(
            "src.mcp.tools.create_rsa.validate_parent_ad_groups_for_rsa_create",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.mcp.tools.create_rsa.create_pending",
            AsyncMock(return_value="TOKENRSA"),
        ),
        patch("src.mcp.tools.create_rsa.connection.get_pool") as mock_pool,
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        result = await create_rsa({"customer_id": "1234567890", "rsas": [_sample_rsa()]})

    assert result["status"] == "dry_run"
    assert result["confirmation_token"] == "TOKENRSA"
    assert result["operation"] == "create_rsa"
    assert len(result["rsas_preview"]) == 1
    assert result["rsas_preview"][0]["headlines_count"] == 5
    assert result["rsas_preview"][0]["descriptions_count"] == 2
    assert result["rsas_preview"][0]["status"] == "PAUSED"


@pytest.mark.asyncio
async def test_returns_error_on_preflight_rejection(_ctx) -> None:
    """Pre-flight error → tool returns error response."""
    from src.mcp.tools.create_rsa import create_rsa

    with patch(
        "src.mcp.tools.create_rsa.validate_parent_ad_groups_for_rsa_create",
        AsyncMock(return_value="Ad_group 999 nao encontrado..."),
    ):
        result = await create_rsa(
            {
                "customer_id": "1234567890",
                "rsas": [_sample_rsa(ad_group_id="999")],
            }
        )

    assert result["status"] == "error"
    assert "999 nao encontrado" in result["error"]
    assert result["operation"] == "create_rsa"


@pytest.mark.asyncio
async def test_builds_correct_blast_summary_for_mixed_batch(_ctx) -> None:
    """Mixed batch (diff ad_groups, statuses, headline counts) → summary reflects distribution."""
    from src.mcp.tools.create_rsa import create_rsa

    with (
        patch(
            "src.mcp.tools.create_rsa.validate_parent_ad_groups_for_rsa_create",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.mcp.tools.create_rsa.create_pending",
            AsyncMock(return_value="TOKEN"),
        ),
        patch("src.mcp.tools.create_rsa.connection.get_pool") as mock_pool,
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        result = await create_rsa(
            {
                "customer_id": "1234567890",
                "rsas": [
                    _sample_rsa(ad_group_id="100", headlines=["H1", "H2", "H3"]),
                    _sample_rsa(ad_group_id="100", status="ENABLED"),
                    _sample_rsa(ad_group_id="200"),
                ],
            }
        )

    assert "3 RSA(s)" in result["blast_summary"]
    assert "2 ad_group(s)" in result["blast_summary"]
    assert "PAUSED(2)" in result["blast_summary"]
    assert "ENABLED(1)" in result["blast_summary"]
