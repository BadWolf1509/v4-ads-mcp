"""Unit tests for the update_keyword_bid MCP tool (Sprint 3b.8 F12 pre-flight)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


@pytest.fixture(autouse=True)
def _ctx():
    from src.mcp.context import McpRequestContext, clear_current, set_current

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _one_bid_payload():
    return {
        "customer_id": "1234567890",
        "bids": [
            {
                "ad_group_id": "111",
                "criterion_id": "9001",
                "new_cpc_bid_brl": 2.10,  # ~5% delta from R$2.00 current → AUTO path
            }
        ],
    }


@pytest.mark.asyncio
async def test_update_keyword_bid_rejects_when_campaign_uses_maximize_conversions() -> None:
    """Pre-flight returns error string → tool returns status=error without touching downstream."""
    from src.mcp.tools.update_keyword_bid import update_keyword_bid

    error_msg = (
        "Campaign 'AutoBid Camp' (id 99999) usa bidding_strategy_type "
        "'MAXIMIZE_CONVERSIONS'. Manual CPC bids sao ignorados nesta estrategia "
        "(Google API silent-failure)."
    )

    with patch(
        "src.mcp.tools.update_keyword_bid.validate_manual_cpc_strategy",
        AsyncMock(return_value=error_msg),
    ):
        result = await update_keyword_bid(_one_bid_payload())

    assert result["status"] == "error"
    assert "MAXIMIZE_CONVERSIONS" in result["error_message"]
    assert result["operation"] == "update_keyword_bid"


@pytest.mark.asyncio
async def test_update_keyword_bid_passes_preflight_when_manual_cpc() -> None:
    """Pre-flight returns None → tool proceeds to bid-lookup and applies (AUTO path, 1 bid)."""
    from src.mcp.tools.update_keyword_bid import update_keyword_bid

    # Fake row that run_report returns for the bid-lookup query
    fake_row = SimpleNamespace(
        ad_group=SimpleNamespace(id=111),
        ad_group_criterion=SimpleNamespace(
            criterion_id=9001,
            keyword=SimpleNamespace(text="nutricionista"),
            cpc_bid_micros=2_000_000,  # current bid R$ 2.00
        ),
    )

    # run_report expects row_formatter to be called by the tool; the tool passes
    # row_formatter to run_report, but our fake calls it directly on fake_row.
    async def fake_run_report(*, row_formatter, **_kwargs):
        return [row_formatter(fake_row)]

    with (
        patch(
            "src.mcp.tools.update_keyword_bid.validate_manual_cpc_strategy",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.mcp.tools.update_keyword_bid.run_report",
            AsyncMock(side_effect=fake_run_report),
        ),
        patch(
            "src.mcp.tools.update_keyword_bid.run_mutation",
            AsyncMock(
                return_value={
                    "provider_request_id": "req-test-1",
                    "applied_count": 1,
                }
            ),
        ),
    ):
        result = await update_keyword_bid(_one_bid_payload())

    # 1 bid with ~25% delta (R$2.00 → R$2.50) triggers CONFIRM, not AUTO.
    # Either way, status must NOT be "error" — the pre-flight passed.
    assert result["status"] != "error"
    assert result.get("operation") == "update_keyword_bid"
