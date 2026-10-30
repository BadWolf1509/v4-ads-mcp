"""dismiss_recommendation so dispensa recomendacao da conta informada."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current
from src.mcp.tools import dismiss_recommendation as mod


@pytest.fixture(autouse=True)
def _ctx():
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


@pytest.mark.asyncio
async def test_dismiss_recusa_recomendacao_de_outra_conta():
    run = AsyncMock()
    with patch.object(mod, "run_recommendation_action", run):
        r = await mod.dismiss_recommendation(
            {
                "customer_id": "1111111111",
                "recommendation_resource_name": "customers/2222222222/recommendations/x",
            }
        )
    assert r["status"] == "error"
    assert "pertence a outra conta" in r["error_message"]
    assert "customers/1111111111/" in r["error_message"]
    assert "customers/2222222222/recommendations/x" in r["error_message"]
    run.assert_not_called()


@pytest.mark.asyncio
async def test_dismiss_da_propria_conta_executa():
    run = AsyncMock(return_value={"applied_count": 1, "provider_request_id": "r"})
    with patch.object(mod, "run_recommendation_action", run):
        r = await mod.dismiss_recommendation(
            {
                "customer_id": "1111111111",
                "recommendation_resource_name": "customers/1111111111/recommendations/x",
            }
        )
    assert r["status"] == "applied"
    run.assert_awaited_once()
