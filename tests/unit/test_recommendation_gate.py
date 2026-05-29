"""Unit test — run_recommendation_action propagates AccountAccessDeniedError.

FIX 1: ensure_account_access gate must fire before before_call / build_client.
Mirror of test_executor_gates.py pattern.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.google_ads.access import AccountAccessDeniedError


@pytest.mark.asyncio
async def test_run_recommendation_action_denies_without_access():
    from src.google_ads import mutations

    mock_pool = MagicMock()
    mock_conn_cm = MagicMock()
    mock_conn_cm.__aenter__ = AsyncMock(return_value=AsyncMock())
    mock_conn_cm.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value = mock_conn_cm

    with (
        patch("src.google_ads.mutations.connection.get_pool", return_value=mock_pool),
        patch(
            "src.google_ads.mutations.ensure_account_access",
            AsyncMock(side_effect=AccountAccessDeniedError("sem acesso")),
        ),
        pytest.raises(AccountAccessDeniedError),
    ):
        await mutations.run_recommendation_action(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="999",
            operation_type="apply_recommendation",
            payload={},
        )
