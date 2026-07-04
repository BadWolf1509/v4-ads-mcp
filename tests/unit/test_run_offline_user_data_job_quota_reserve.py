"""F73: quota leak fix + cap por gestor em run_offline_user_data_job (customer_match.py).

Bug original: before_call (reserva) ficava DENTRO do try, mas o caminho de erro
chamava record_actual(actual_ops=0, estimated_ops=N) incondicionalmente mesmo
quando a reserva nunca foi persistida (QuotaExhausted bloqueou antes). Fix:
reserved=False ate AMBAS as reservas (global + `mgr:<uuid>`) completarem;
record_actual so roda `if reserved`. Audit continua rodando sempre (raise
apos o audit — run_offline_user_data_job propaga o erro, nao retorna dict).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.governance.rate_limit import QuotaExhausted


def _pool_with_transactable_conn() -> MagicMock:
    fake_conn = AsyncMock()
    fake_txn_cm = MagicMock()
    fake_txn_cm.__aenter__ = AsyncMock(return_value=None)
    fake_txn_cm.__aexit__ = AsyncMock(return_value=None)
    fake_conn.transaction = MagicMock(return_value=fake_txn_cm)

    mock_pool = MagicMock()
    mock_acquire_cm = MagicMock()
    mock_acquire_cm.__aenter__ = AsyncMock(return_value=fake_conn)
    mock_acquire_cm.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value = mock_acquire_cm
    return mock_pool


def _make_capture_client_with_offline_user_data_job_service() -> tuple[MagicMock, MagicMock]:
    from tests.unit.fixtures.proto_capture import make_capture_client

    client = make_capture_client()
    service = MagicMock()
    service.create_offline_user_data_job = MagicMock(
        return_value=MagicMock(resource_name="customers/1163862076/offlineUserDataJobs/JOB123")
    )
    service.add_offline_user_data_job_operations = MagicMock(return_value=MagicMock())
    service.run_offline_user_data_job = MagicMock(return_value=MagicMock())

    _original_get_service = client.get_service

    def _get_service(name: str) -> MagicMock:
        if name == "OfflineUserDataJobService":
            return service
        return _original_get_service(name)

    client.get_service = _get_service
    client.enums.OfflineUserDataJobTypeEnum.CUSTOMER_MATCH_USER_LIST = "CUSTOMER_MATCH_USER_LIST"
    client.enums.ConsentStatusEnum.GRANTED = "GRANTED"
    return client, service


@pytest.mark.asyncio
async def test_quota_exhausted_blocks_and_skips_record_actual():
    """F73: se before_call (reserva GLOBAL) levanta QuotaExhausted, record_actual
    NAO deve ser chamado (nao ha reserva persistida pra reconciliar)."""
    from src.google_ads.customer_match import run_offline_user_data_job
    from src.google_ads.errors import GoogleAdsFriendlyError

    before_call_mock = AsyncMock(side_effect=QuotaExhausted("quota diaria esgotada"))
    record_actual_mock = AsyncMock()
    audit_mock = AsyncMock(return_value=1)

    with (
        patch("src.google_ads.customer_match.ensure_account_access", AsyncMock()),
        patch("src.google_ads.customer_match.before_call", before_call_mock),
        patch("src.google_ads.customer_match.record_actual", record_actual_mock),
        patch("src.google_ads.customer_match.audit_log.record", audit_mock),
        patch(
            "src.google_ads.customer_match.connection.get_pool",
            return_value=_pool_with_transactable_conn(),
        ),
        pytest.raises(GoogleAdsFriendlyError),
    ):
        await run_offline_user_data_job(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1163862076",
            user_list_id="1234567890",
            operation_type="add",
            hashed_members=[{"hashed_email": "abc123"}],
        )

    record_actual_mock.assert_not_awaited()
    # run_offline_user_data_job SEMPRE audita (mutate PII/LGPD) -- status=error.
    audit_mock.assert_awaited_once()
    assert audit_mock.call_args.kwargs["status"] == "error"


@pytest.mark.asyncio
async def test_success_reserves_and_reconciles_both_global_and_manager_keys():
    """F73(b): sucesso -> before_call 2x (global + mgr:<uuid>) e record_actual 2x."""
    from src.config import get_settings
    from src.google_ads.customer_match import run_offline_user_data_job

    manager_id = uuid4()
    client, _service = _make_capture_client_with_offline_user_data_job_service()
    before_call_mock = AsyncMock()
    record_actual_mock = AsyncMock()

    with (
        patch("src.google_ads.customer_match.ensure_account_access", AsyncMock()),
        patch("src.google_ads.customer_match.before_call", before_call_mock),
        patch("src.google_ads.customer_match.record_actual", record_actual_mock),
        patch("src.google_ads.customer_match.audit_log.record", AsyncMock(return_value=1)),
        patch(
            "src.google_ads.customer_match.connection.get_pool",
            return_value=_pool_with_transactable_conn(),
        ),
        patch(
            "src.google_ads.customer_match.build_client_for_manager",
            AsyncMock(return_value=client),
        ),
    ):
        result = await run_offline_user_data_job(
            manager_id=manager_id,
            session_id=uuid4(),
            customer_id="1163862076",
            user_list_id="1234567890",
            operation_type="add",
            hashed_members=[{"hashed_email": "abc123"}],
        )

    assert result["job_resource_name"] == "customers/1163862076/offlineUserDataJobs/JOB123"
    settings = get_settings()
    assert before_call_mock.await_count == 2
    mgr_call = next(c for c in before_call_mock.await_args_list if c.args[1] == f"mgr:{manager_id}")
    assert mgr_call.kwargs["daily_limit"] == settings.manager_daily_quota

    assert record_actual_mock.await_count == 2
    reconciled_keys = {c.args[1] for c in record_actual_mock.await_args_list}
    assert f"mgr:{manager_id}" in reconciled_keys
