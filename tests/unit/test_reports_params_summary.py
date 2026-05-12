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
        patch.object(reports.connection, "get_pool"),
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
        patch.object(reports.connection, "get_pool"),
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
