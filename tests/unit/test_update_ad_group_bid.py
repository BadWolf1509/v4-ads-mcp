"""Unit tests for the update_ad_group_bid MCP tool (Sprint 3b.8 F12 pre-flight)."""

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
                "ad_group_id": "1",
                "new_cpc_bid_brl": 1.05,  # ~5% delta from R$1.00 current → AUTO path
            }
        ],
    }


@pytest.mark.asyncio
async def test_update_ad_group_bid_rejects_when_campaign_uses_target_cpa() -> None:
    """Pre-flight returns error string → tool returns status=error without touching downstream."""
    from src.mcp.tools.update_ad_group_bid import update_ad_group_bid

    error_msg = (
        "Campaign 'SmartBid Camp' (id 88888) usa bidding_strategy_type "
        "'TARGET_CPA'. Manual CPC bids sao ignorados nesta estrategia "
        "(Google API silent-failure)."
    )

    with patch(
        "src.mcp.tools.update_ad_group_bid.validate_manual_cpc_strategy",
        AsyncMock(return_value=error_msg),
    ):
        result = await update_ad_group_bid(_one_bid_payload())

    assert result["status"] == "error"
    assert "TARGET_CPA" in result["error"]
    assert result["operation"] == "update_ad_group_bid"


@pytest.mark.asyncio
async def test_update_ad_group_bid_passes_preflight_when_manual_cpc() -> None:
    """Pre-flight returns None → tool proceeds to bid-lookup and applies (AUTO path, 1 bid)."""
    from src.mcp.tools.update_ad_group_bid import update_ad_group_bid

    # Fake row that run_report returns for the bid-lookup query
    fake_row = SimpleNamespace(
        ad_group=SimpleNamespace(
            id=1,
            name="Nutricionista - Brand",
            cpc_bid_micros=1_000_000,  # current bid R$ 1.00
        ),
    )

    # run_report expects row_formatter to be called by the tool; the tool passes
    # row_formatter to run_report, but our fake calls it directly on fake_row.
    async def fake_run_report(*, row_formatter, **_kwargs):
        return [row_formatter(fake_row)]

    with (
        patch(
            "src.mcp.tools.update_ad_group_bid.validate_manual_cpc_strategy",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.mcp.tools.update_ad_group_bid.run_report",
            AsyncMock(side_effect=fake_run_report),
        ),
        patch(
            "src.mcp.tools.update_ad_group_bid.run_mutation",
            AsyncMock(
                return_value={
                    "google_request_id": "req-test-1",
                    "applied_count": 1,
                }
            ),
        ),
    ):
        result = await update_ad_group_bid(_one_bid_payload())

    # 1 bid with ~5% delta (R$1.00 → R$1.05) triggers AUTO path.
    # Either way, status must NOT be "error" — the pre-flight passed.
    assert result["status"] != "error"
    assert result.get("operation") == "update_ad_group_bid"
