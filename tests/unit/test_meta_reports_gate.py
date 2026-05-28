from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.meta_ads import reports
from src.meta_ads.client import MetaAccessDeniedError


@pytest.mark.asyncio
async def test_run_meta_graph_get_denies_without_grant():
    mid, sid = uuid4(), uuid4()

    # Mock acquire() context manager that returns a fake conn
    fake_conn = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=fake_conn)
    cm.__aexit__ = AsyncMock(return_value=False)

    fake_pool = MagicMock()
    fake_pool.acquire = MagicMock(return_value=cm)

    with (
        patch(
            "src.meta_ads.reports.manager_meta_account_access.can_manager_access",
            AsyncMock(return_value=False),
        ),
        patch("src.meta_ads.reports.connection.get_pool", return_value=fake_pool),
        pytest.raises(MetaAccessDeniedError),
    ):
        await reports.run_meta_graph_get(
            manager_id=mid,
            session_id=sid,
            edge="/act_999/insights",
            params={"ad_account_id": "act_999"},
            operation_name="meta_get_campaign_performance",
        )


@pytest.mark.asyncio
async def test_run_meta_graph_get_deny_writes_audit_log():
    """deny path with audit_this_call=True must raise AND call audit_log.record(status='denied')."""
    mid, sid = uuid4(), uuid4()

    fake_conn = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=fake_conn)
    cm.__aexit__ = AsyncMock(return_value=False)

    fake_pool = MagicMock()
    fake_pool.acquire = MagicMock(return_value=cm)

    mock_audit_record = AsyncMock()

    with (
        patch(
            "src.meta_ads.reports.manager_meta_account_access.can_manager_access",
            AsyncMock(return_value=False),
        ),
        patch("src.meta_ads.reports.connection.get_pool", return_value=fake_pool),
        patch("src.meta_ads.reports.audit_log.record", mock_audit_record),
        pytest.raises(MetaAccessDeniedError),
    ):
        await reports.run_meta_graph_get(
            manager_id=mid,
            session_id=sid,
            edge="/act_999/insights",
            params={"ad_account_id": "act_999"},
            operation_name="meta_get_campaign_performance",
            audit_this_call=True,
            params_summary={"ad_account_id": "act_999"},
        )

    mock_audit_record.assert_awaited_once()
    call_kwargs = mock_audit_record.call_args.kwargs
    assert call_kwargs["status"] == "denied"
    assert call_kwargs["manager_id"] == mid
    assert call_kwargs["session_id"] == sid
    assert call_kwargs["platform"] == "meta"
