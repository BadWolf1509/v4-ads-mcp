"""F73: quota leak fix + cap por gestor em run_report (src/google_ads/reports.py).

Bug original: before_call (reserva) ficava DENTRO do try, e o raise de
QuotaExhausted acontecia ANTES de qualquer persistência (a transação interna
de before_call fazia rollback do próprio INSERT/UPDATE). Mas o finally do
executor chamava record_actual(actual_ops=0, estimated_ops=N) incondicionalmente,
que aplica delta -N no contador (GREATEST(0, operations_used + delta)) mesmo
sem reserva correspondente. Resultado: bloqueio no teto decrementava o contador
sem nunca ter incrementado -> "uma bloqueia, a próxima passa".

Fix: reserved=False até AMBAS as reservas (global + `mgr:<uuid>`) completarem
dentro de uma transação externa (before_call já abre uma interna -> vira
SAVEPOINT). record_actual só roda `if reserved`, reconciliando as DUAS chaves.
Audit continua rodando sempre (a negação por quota deve aparecer no audit).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.governance.rate_limit import QuotaExhausted


def _pool_with_conn() -> tuple[MagicMock, AsyncMock]:
    """Mock pool.acquire() returning an async-context-manager yielding a fake conn.

    fake_conn.transaction() must itself return a real async context manager
    (not a coroutine) — asyncpg's Connection.transaction() is a sync method
    that returns a Transaction object usable via `async with`.
    """
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
    return mock_pool, fake_conn


def _common_patches(*, before_call_mock: AsyncMock, record_actual_mock: AsyncMock):
    mock_pool, _ = _pool_with_conn()
    return [
        patch("src.google_ads.reports.ensure_account_access", AsyncMock(return_value=None)),
        patch("src.google_ads.reports.before_call", before_call_mock),
        patch("src.google_ads.reports.record_actual", record_actual_mock),
        patch("src.google_ads.reports.audit_log.record", AsyncMock(return_value=1)),
        patch("src.google_ads.reports.connection.get_pool", return_value=mock_pool),
    ]


def _fake_client_streaming(rows: list[Any]) -> MagicMock:
    client = MagicMock()

    def _row_formatter(row: Any) -> dict[str, Any]:
        return {"value": row}

    batch = MagicMock()
    batch.results = rows
    ga_service = MagicMock()
    ga_service.search_stream = MagicMock(return_value=[batch])
    client.get_service = MagicMock(return_value=ga_service)
    client.get_type = MagicMock(return_value=MagicMock())
    return client, _row_formatter


@pytest.mark.asyncio
async def test_quota_exhausted_blocks_before_client_build_and_skips_record_actual():
    """F73: se before_call (reserva GLOBAL) levanta QuotaExhausted, record_actual
    NUNCA deve ser chamado (nao ha reserva persistida pra reconciliar)."""
    from src.google_ads.reports import run_report

    before_call_mock = AsyncMock(side_effect=QuotaExhausted("quota diaria esgotada"))
    record_actual_mock = AsyncMock()

    patches = _common_patches(
        before_call_mock=before_call_mock, record_actual_mock=record_actual_mock
    )
    for p in patches:
        p.start()
    try:
        with pytest.raises(QuotaExhausted):
            await run_report(
                manager_id=uuid4(),
                session_id=uuid4(),
                customer_id="1234567890",
                query="SELECT campaign.id FROM campaign",
                row_formatter=lambda r: {"id": r},
                operation_name="get_campaign_performance",
                estimated_ops=1,
                audit_this_call=True,
            )
    finally:
        for p in patches:
            p.stop()

    record_actual_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_quota_exhausted_still_audits_with_status_error_when_opted_in():
    """F73: audit_this_call=True -> mesmo com quota bloqueada, o audit grava
    status='error' (a negacao deve ser visivel no audit log)."""
    from src.google_ads.reports import run_report

    before_call_mock = AsyncMock(side_effect=QuotaExhausted("quota diaria esgotada"))
    record_actual_mock = AsyncMock()
    audit_mock = AsyncMock(return_value=1)

    patches = [
        patch("src.google_ads.reports.ensure_account_access", AsyncMock(return_value=None)),
        patch("src.google_ads.reports.before_call", before_call_mock),
        patch("src.google_ads.reports.record_actual", record_actual_mock),
        patch("src.google_ads.reports.audit_log.record", audit_mock),
        patch("src.google_ads.reports.connection.get_pool", return_value=_pool_with_conn()[0]),
    ]
    for p in patches:
        p.start()
    try:
        with pytest.raises(QuotaExhausted):
            await run_report(
                manager_id=uuid4(),
                session_id=uuid4(),
                customer_id="1234567890",
                query="SELECT campaign.id FROM campaign",
                row_formatter=lambda r: {"id": r},
                operation_name="run_gaql",
                estimated_ops=1,
                audit_this_call=True,
            )
    finally:
        for p in patches:
            p.stop()

    audit_mock.assert_awaited_once()
    assert audit_mock.call_args.kwargs["status"] == "error"


@pytest.mark.asyncio
async def test_success_reserves_and_reconciles_both_global_and_manager_keys():
    """F73(b): sucesso -> before_call 2x (global + mgr:<uuid> com daily_limit do
    settings) e record_actual 2x com as mesmas chaves."""
    from src.config import get_settings
    from src.google_ads.reports import run_report

    manager_id = uuid4()
    client, row_formatter = _fake_client_streaming([1, 2, 3])
    before_call_mock = AsyncMock()
    record_actual_mock = AsyncMock()

    patches = [
        patch("src.google_ads.reports.ensure_account_access", AsyncMock(return_value=None)),
        patch("src.google_ads.reports.before_call", before_call_mock),
        patch("src.google_ads.reports.record_actual", record_actual_mock),
        patch("src.google_ads.reports.audit_log.record", AsyncMock(return_value=1)),
        patch("src.google_ads.reports.connection.get_pool", return_value=_pool_with_conn()[0]),
        patch("src.google_ads.reports.build_client_for_manager", AsyncMock(return_value=client)),
    ]
    for p in patches:
        p.start()
    try:
        await run_report(
            manager_id=manager_id,
            session_id=uuid4(),
            customer_id="1234567890",
            query="SELECT campaign.id FROM campaign",
            row_formatter=row_formatter,
            operation_name="get_campaign_performance",
            estimated_ops=1,
            audit_this_call=False,
        )
    finally:
        for p in patches:
            p.stop()

    settings = get_settings()
    assert before_call_mock.await_count == 2
    keys_called = {c.args[1] for c in before_call_mock.await_args_list}
    assert keys_called == {before_call_mock.await_args_list[0].args[1], f"mgr:{manager_id}"}
    # segunda chamada deve ser a chave do gestor com o daily_limit configurado
    mgr_call = next(c for c in before_call_mock.await_args_list if c.args[1] == f"mgr:{manager_id}")
    assert mgr_call.kwargs["daily_limit"] == settings.manager_daily_quota

    assert record_actual_mock.await_count == 2
    reconciled_keys = {c.args[1] for c in record_actual_mock.await_args_list}
    assert f"mgr:{manager_id}" in reconciled_keys
