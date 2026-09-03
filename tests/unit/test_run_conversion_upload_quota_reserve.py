"""F73: quota leak fix + cap por gestor em run_conversion_upload (conversions.py).

Bug original: before_call (reserva) ficava DENTRO do try, mas o caminho de erro
chamava record_actual(actual_ops=0, estimated_ops=N) incondicionalmente mesmo
quando a reserva nunca foi persistida (QuotaExhausted bloqueou antes). Fix:
reserved=False ate AMBAS as reservas (global + `mgr:<uuid>`) completarem;
record_actual so roda `if reserved`. Audit continua rodando sempre.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.governance.rate_limit import QuotaExhausted


def _payload():
    return {
        "customer_id": "1234567890",
        "conversion_action_id": "987654321",
        "__time_zone__": "America/Sao_Paulo",  # F146
        "conversions": [
            {
                "gclid": "Cj0KCQjwTEST_001",
                "conversion_date_time": "2026-05-17 14:30:00",
                "conversion_value_brl": 100.0,
            }
        ],
    }


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


def _mock_client_with_success_response(num_conversions: int = 1) -> MagicMock:
    client = MagicMock()
    client.get_type = MagicMock(side_effect=lambda name: MagicMock())
    client.enums.ConsentStatusEnum.GRANTED = "GRANTED"

    response = MagicMock()
    results = []
    for i in range(num_conversions):
        r = MagicMock()
        r.conversion_action = "customers/1234567890/conversionActions/987654321"
        r.gclid = f"Cj0KCQjwTEST_{i:03d}"
        results.append(r)
    response.results = results
    pfe = MagicMock()
    pfe.code = 0
    pfe.details = []
    response.partial_failure_error = pfe

    service = MagicMock()
    service.upload_click_conversions = MagicMock(return_value=response)
    client.get_service = MagicMock(return_value=service)
    return client


@pytest.mark.asyncio
async def test_quota_exhausted_blocks_and_skips_record_actual():
    """F73: se before_call (reserva GLOBAL) levanta QuotaExhausted, record_actual
    NAO deve ser chamado (nao ha reserva persistida pra reconciliar)."""
    from src.google_ads.conversions import run_conversion_upload

    before_call_mock = AsyncMock(side_effect=QuotaExhausted("quota diaria esgotada"))
    record_actual_mock = AsyncMock()
    audit_mock = AsyncMock(return_value=1)

    patches = [
        patch("src.google_ads.conversions.ensure_account_access", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.before_call", before_call_mock),
        patch("src.google_ads.conversions.record_actual", record_actual_mock),
        patch("src.google_ads.conversions.audit_log.record", audit_mock),
        patch(
            "src.google_ads.conversions.connection.get_pool",
            return_value=_pool_with_transactable_conn(),
        ),
    ]
    for p in patches:
        p.start()
    try:
        result = await run_conversion_upload(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="import_offline_conversions",
            payload=_payload(),
            target_count=1,
            params_summary={"conversion_count": 1},
        )
    finally:
        for p in patches:
            p.stop()

    record_actual_mock.assert_not_awaited()
    # run_conversion_upload SEMPRE audita (mutate sensivel) -- status=error na negacao.
    audit_mock.assert_awaited_once()
    assert audit_mock.call_args.kwargs["status"] == "error"
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_success_reserves_and_reconciles_both_global_and_manager_keys():
    """F73(b): sucesso -> before_call 2x (global + mgr:<uuid>) e record_actual 2x."""
    from src.config import get_settings
    from src.google_ads.conversions import run_conversion_upload

    manager_id = uuid4()
    client = _mock_client_with_success_response(1)
    before_call_mock = AsyncMock()
    record_actual_mock = AsyncMock()

    patches = [
        patch("src.google_ads.conversions.ensure_account_access", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.before_call", before_call_mock),
        patch("src.google_ads.conversions.record_actual", record_actual_mock),
        patch("src.google_ads.conversions.audit_log.record", AsyncMock(return_value=1)),
        patch(
            "src.google_ads.conversions.connection.get_pool",
            return_value=_pool_with_transactable_conn(),
        ),
        patch(
            "src.google_ads.conversions.build_client_for_manager",
            AsyncMock(return_value=client),
        ),
        patch("src.google_ads.conversions.get_request_id", return_value="req-001"),
        patch("src.google_ads.conversions.reset_request_id", return_value=None),
    ]
    for p in patches:
        p.start()
    try:
        result = await run_conversion_upload(
            manager_id=manager_id,
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="import_offline_conversions",
            payload=_payload(),
            target_count=1,
            params_summary={"conversion_count": 1},
        )
    finally:
        for p in patches:
            p.stop()

    assert result["status"] == "applied"
    settings = get_settings()
    assert before_call_mock.await_count == 2
    mgr_call = next(c for c in before_call_mock.await_args_list if c.args[1] == f"mgr:{manager_id}")
    assert mgr_call.kwargs["daily_limit"] == settings.manager_daily_quota

    assert record_actual_mock.await_count == 2
    reconciled_keys = {c.args[1] for c in record_actual_mock.await_args_list}
    assert f"mgr:{manager_id}" in reconciled_keys
