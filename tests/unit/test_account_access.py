from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.google_ads import access
from src.google_ads.access import AccountAccessDeniedError


@pytest.mark.asyncio
async def test_ensure_account_access_allows_when_granted():
    conn = AsyncMock()
    with patch(
        "src.google_ads.access.manager_account_access.can_manager_access",
        AsyncMock(return_value=True),
    ):
        await access.ensure_account_access(
            conn,
            manager_id=uuid4(),
            customer_id="123",
            session_id=uuid4(),
            operation_name="get_campaign_performance",
            level="read",
        )


@pytest.mark.asyncio
async def test_ensure_account_access_denies_and_audits():
    conn = AsyncMock()
    mid, sid = uuid4(), uuid4()
    with (
        patch(
            "src.google_ads.access.manager_account_access.can_manager_access",
            AsyncMock(return_value=False),
        ),
        patch("src.google_ads.access.audit_log.record", AsyncMock()) as rec,
    ):
        with pytest.raises(AccountAccessDeniedError):
            await access.ensure_account_access(
                conn,
                manager_id=mid,
                customer_id="999",
                session_id=sid,
                operation_name="update_campaign_status",
                level="write",
            )
        rec.assert_awaited_once()
        kwargs = rec.await_args.kwargs
        assert kwargs["status"] == "denied"
        assert kwargs["customer_id"] == "999"
        assert kwargs["platform"] == "google"
