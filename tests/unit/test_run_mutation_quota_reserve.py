"""F73: quota leak fix + cap por gestor em run_mutation (src/google_ads/mutations.py).

run_mutation ja era IMUNE ao quota leak por acidente (o finally reconciliava
actual_ops=target_count == estimated_ops -> delta 0, entao record_actual virava
no-op mesmo sem reserva). Mas o mesmo refactor (reserved-gate + cap por gestor)
e aplicado aqui por consistencia com os outros 3 executores, preservando a
semantica atual do finally (actual_ops=target_count).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.governance.rate_limit import QuotaExhausted


def _pool_with_transactable_conn() -> MagicMock:
    """conn.transaction() precisa ser um async CM real (nao coroutine bare)."""
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


def _fake_success_client() -> MagicMock:
    client = MagicMock()
    fake_response = MagicMock()
    fake_response.mutate_operation_responses = []
    fake_response.partial_failure_error = MagicMock(code=0, details=[])
    fake_service = MagicMock()
    fake_service.mutate = MagicMock(return_value=fake_response)
    client.get_service = MagicMock(return_value=fake_service)
    client.get_type = MagicMock(return_value=MagicMock(mutate_operations=[]))
    return client


@pytest.mark.asyncio
async def test_quota_exhausted_blocks_before_builder_and_skips_record_actual():
    """F73: se before_call (reserva GLOBAL) levanta QuotaExhausted, record_actual
    NAO deve ser chamado (nao ha reserva persistida pra reconciliar)."""
    from src.google_ads import mutations
    from src.google_ads.mutations import run_mutation

    before_call_mock = AsyncMock(side_effect=QuotaExhausted("quota diaria esgotada"))
    record_actual_mock = AsyncMock()

    with (
        patch.object(mutations, "ensure_account_access", AsyncMock()),
        patch.object(mutations, "before_call", before_call_mock),
        patch.object(mutations, "record_actual", record_actual_mock),
        patch.object(mutations.audit_log, "record", AsyncMock(return_value=1)) as audit_mock,
        patch.object(mutations.connection, "get_pool", return_value=_pool_with_transactable_conn()),
        pytest.raises(QuotaExhausted),
    ):
        await run_mutation(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="update_keyword_status",
            payload={"keywords": [{}]},
            target_count=1,
        )

    record_actual_mock.assert_not_awaited()
    # run_mutation sempre audita (mutate sensivel) -- status=error na negacao.
    audit_mock.assert_awaited_once()
    assert audit_mock.call_args.kwargs["status"] == "error"


@pytest.mark.asyncio
async def test_success_reserves_and_reconciles_both_global_and_manager_keys():
    """F73(b): sucesso -> before_call 2x (global + mgr:<uuid>) e record_actual 2x
    preservando actual_ops=target_count (semantica atual do finally)."""
    from src.config import get_settings
    from src.google_ads import mutations
    from src.google_ads.mutations import run_mutation

    manager_id = uuid4()
    client = _fake_success_client()
    before_call_mock = AsyncMock()
    record_actual_mock = AsyncMock()

    with (
        patch.object(mutations, "ensure_account_access", AsyncMock()),
        patch.object(mutations, "before_call", before_call_mock),
        patch.object(mutations, "record_actual", record_actual_mock),
        patch.object(mutations.audit_log, "record", AsyncMock(return_value=1)),
        patch.object(mutations.connection, "get_pool", return_value=_pool_with_transactable_conn()),
        patch.object(mutations, "build_client_for_manager", AsyncMock(return_value=client)),
        patch.object(mutations, "get_builder", lambda _op: lambda c, cid, p: [MagicMock()]),
        patch.object(mutations, "get_request_id", lambda: "fake-req-id"),
        patch.object(mutations, "reset_request_id", lambda: None),
    ):
        await run_mutation(
            manager_id=manager_id,
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="update_keyword_status",
            payload={"keywords": [{}]},
            target_count=3,
        )

    settings = get_settings()
    assert before_call_mock.await_count == 2
    mgr_call = next(c for c in before_call_mock.await_args_list if c.args[1] == f"mgr:{manager_id}")
    assert mgr_call.kwargs["estimated_ops"] == 3
    assert mgr_call.kwargs["daily_limit"] == settings.manager_daily_quota

    assert record_actual_mock.await_count == 2
    for call in record_actual_mock.await_args_list:
        assert call.kwargs["actual_ops"] == 3
        assert call.kwargs["estimated_ops"] == 3
    reconciled_keys = {c.args[1] for c in record_actual_mock.await_args_list}
    assert f"mgr:{manager_id}" in reconciled_keys
