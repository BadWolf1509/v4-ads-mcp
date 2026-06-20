"""A negação de acesso Meta deve emitir log.warning (espelha o gate Google)."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from structlog.testing import capture_logs

from src.meta_ads import reports as meta_reports


class _FakeAcquire:
    async def __aenter__(self) -> MagicMock:
        return MagicMock()

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakePool:
    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire()


@pytest.mark.asyncio
async def test_meta_denial_emits_warning_log(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(meta_reports.connection, "get_pool", lambda: _FakePool())
    monkeypatch.setattr(
        meta_reports.manager_meta_account_access,
        "can_manager_access",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(meta_reports.audit_log, "record", AsyncMock(return_value=1))

    with capture_logs() as logs, pytest.raises(meta_reports.MetaAccessDeniedError):
        await meta_reports.run_meta_graph_get(
            manager_id=uuid4(),
            session_id=uuid4(),
            edge="/act_123/insights",
            params={"ad_account_id": "act_123"},
            operation_name="meta_get_campaign_performance",
        )

    events = [e for e in logs if e["event"] == "meta_account_access_denied"]
    assert len(events) == 1
    assert events[0]["ad_account_id"] == "act_123"
