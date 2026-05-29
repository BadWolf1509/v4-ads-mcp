"""Unit tests proving each Google executor propagates AccountAccessDeniedError.

T2 run_report, T3 run_mutation, T4a run_conversion_upload, T4b run_offline_user_data_job.

Pattern: patch ensure_account_access to raise + patch connection.get_pool so
the async-context-manager inside the gate doesn't blow up, then assert the error
propagates unchanged out of the executor.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.google_ads.access import AccountAccessDeniedError

# ---------------------------------------------------------------------------
# T2 — run_report
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_report_denies_without_access():
    from src.google_ads import reports

    mock_pool = MagicMock()
    mock_conn_cm = MagicMock()
    mock_conn_cm.__aenter__ = AsyncMock(return_value=MagicMock())
    mock_conn_cm.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value = mock_conn_cm

    with (
        patch("src.google_ads.reports.connection.get_pool", return_value=mock_pool),
        patch(
            "src.google_ads.reports.ensure_account_access",
            AsyncMock(side_effect=AccountAccessDeniedError("sem acesso")),
        ),
        pytest.raises(AccountAccessDeniedError),
    ):
        await reports.run_report(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="999",
            query="SELECT 1",
            row_formatter=lambda r: {},
            operation_name="test_op",
        )


# ---------------------------------------------------------------------------
# T3 — run_mutation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_mutation_denies_without_access():
    from src.google_ads import mutations

    mock_pool = MagicMock()
    mock_conn_cm = MagicMock()
    mock_conn_cm.__aenter__ = AsyncMock(return_value=MagicMock())
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
        await mutations.run_mutation(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="999",
            operation_type="update_campaign_status",
            payload={},
            target_count=1,
        )


# ---------------------------------------------------------------------------
# T4a — run_conversion_upload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_conversion_upload_denies_without_access():
    from src.google_ads import conversions

    mock_pool = MagicMock()
    mock_conn_cm = MagicMock()
    mock_conn_cm.__aenter__ = AsyncMock(return_value=MagicMock())
    mock_conn_cm.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value = mock_conn_cm

    with (
        patch("src.google_ads.conversions.connection.get_pool", return_value=mock_pool),
        patch(
            "src.google_ads.conversions.ensure_account_access",
            AsyncMock(side_effect=AccountAccessDeniedError("sem acesso")),
        ),
        pytest.raises(AccountAccessDeniedError),
    ):
        await conversions.run_conversion_upload(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="999",
            operation_type="import_offline_conversions",
            payload={},
            target_count=1,
        )


# ---------------------------------------------------------------------------
# T4b — run_offline_user_data_job
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_offline_user_data_job_denies_without_access():
    from src.google_ads import customer_match

    mock_pool = MagicMock()
    mock_conn_cm = MagicMock()
    mock_conn_cm.__aenter__ = AsyncMock(return_value=MagicMock())
    mock_conn_cm.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value = mock_conn_cm

    with (
        patch("src.google_ads.customer_match.connection.get_pool", return_value=mock_pool),
        patch(
            "src.google_ads.customer_match.ensure_account_access",
            AsyncMock(side_effect=AccountAccessDeniedError("sem acesso")),
        ),
        pytest.raises(AccountAccessDeniedError),
    ):
        await customer_match.run_offline_user_data_job(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="999",
            user_list_id="1",
            operation_type="add",
            hashed_members=[],
        )
