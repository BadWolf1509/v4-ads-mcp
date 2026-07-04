"""Unit tests for run_report's optional params_summary kwarg.

Mirrors the Sprint 3b.1 extension to run_mutation (commit f156d99).
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


def _fake_client_returning_rows(rows: list[dict]):
    """Mock SDK client whose search_stream yields one batch with the given rows."""
    client = MagicMock()
    fake_service = MagicMock()
    batch = MagicMock(results=[MagicMock(_row=r) for r in rows])
    fake_service.search_stream = MagicMock(return_value=[batch])
    client.get_service = MagicMock(return_value=fake_service)
    client.get_type = MagicMock(return_value=MagicMock())
    return client


def _pool_with_transactable_conn() -> MagicMock:
    """Mock pool whose acquire()'d conn has a real conn.transaction() async CM.

    F73: run_report now wraps both before_call reservations in an external
    `async with pool.acquire() as conn, conn.transaction():` block, so any
    mock conn needs `.transaction()` to return a usable async context manager
    (not a bare MagicMock, which lacks __aenter__/__aexit__).
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
    return mock_pool


@pytest.mark.asyncio
async def test_run_report_uses_custom_params_summary(monkeypatch):
    """When params_summary is provided, audit_log receives it (not None)."""
    from src.google_ads import reports

    custom = {"target_type": "keyword", "query_matched_count": 47, "limit_hit": False}

    monkeypatch.setattr(
        reports,
        "build_client_for_manager",
        AsyncMock(return_value=_fake_client_returning_rows([{"id": "1"}])),
    )

    audit_mock = AsyncMock()
    with (
        patch.object(reports.connection, "get_pool", return_value=_pool_with_transactable_conn()),
        patch.object(reports, "ensure_account_access", AsyncMock()),
        patch.object(reports, "before_call", AsyncMock()),
        patch.object(reports, "record_actual", AsyncMock()),
        patch.object(reports.audit_log, "record", audit_mock),
    ):
        await reports.run_report(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            query="SELECT campaign.id FROM campaign",
            row_formatter=lambda r: {"id": "1"},
            operation_name="bulk_pause_by_query_dry_run",
            audit_this_call=True,
            params_summary=custom,
        )

    assert audit_mock.call_count == 1
    assert audit_mock.call_args.kwargs["params_summary"] == custom


@pytest.mark.asyncio
async def test_run_report_default_params_summary_is_none(monkeypatch):
    """Backward compat: when not provided, audit_log gets params_summary=None."""
    from src.google_ads import reports

    monkeypatch.setattr(
        reports,
        "build_client_for_manager",
        AsyncMock(return_value=_fake_client_returning_rows([{"id": "1"}])),
    )

    audit_mock = AsyncMock()
    with (
        patch.object(reports.connection, "get_pool", return_value=_pool_with_transactable_conn()),
        patch.object(reports, "ensure_account_access", AsyncMock()),
        patch.object(reports, "before_call", AsyncMock()),
        patch.object(reports, "record_actual", AsyncMock()),
        patch.object(reports.audit_log, "record", audit_mock),
    ):
        await reports.run_report(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            query="SELECT campaign.id FROM campaign",
            row_formatter=lambda r: {"id": "1"},
            operation_name="get_recommendations",
            audit_this_call=True,
        )

    assert audit_mock.call_count == 1
    assert audit_mock.call_args.kwargs["params_summary"] is None


@pytest.mark.asyncio
async def test_execute_gaql_raw_builds_params_summary_with_query_and_limit(monkeypatch):
    """Task 1.3: execute_gaql_raw DEVE montar params_summary={'query':..., 'limit':...}
    e repassar pro run_report -- sem isto o audit de run_gaql fica vazio (o bug
    original: params_summary=None mesmo com audit_this_call=True)."""
    from src.google_ads import reports

    run_report_mock = AsyncMock(return_value=[{"id": "1"}])
    monkeypatch.setattr(reports, "run_report", run_report_mock)

    manager_id = uuid4()
    session_id = uuid4()

    await reports.execute_gaql_raw(
        manager_id=manager_id,
        session_id=session_id,
        customer_id="1234567890",
        query="SELECT campaign.id FROM campaign",
        limit=42,
    )

    run_report_mock.assert_awaited_once()
    kwargs = run_report_mock.call_args.kwargs
    assert kwargs["params_summary"] == {
        "query": "SELECT campaign.id FROM campaign",
        "limit": 42,
    }
    assert kwargs["audit_this_call"] is True
    assert kwargs["operation_name"] == "run_gaql"


@pytest.mark.asyncio
async def test_execute_gaql_raw_truncates_query_in_params_summary_at_800_chars(monkeypatch):
    """Query longa (>800 chars) e truncada no params_summary (nao no audit inteiro,
    so o resumo persistido -- protege contra rows gigantes no audit_log)."""
    from src.google_ads import reports

    run_report_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(reports, "run_report", run_report_mock)

    long_query = "SELECT campaign.id FROM campaign WHERE " + "x" * 900

    await reports.execute_gaql_raw(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        query=long_query,
        limit=100,
    )

    kwargs = run_report_mock.call_args.kwargs
    assert kwargs["params_summary"]["query"] == long_query[:800]
    assert len(kwargs["params_summary"]["query"]) == 800
