"""resync_meta() grava 1 audit_log de job (operation=meta_resync, platform=meta)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.jobs import meta_resync


class _FakeAcquire:
    async def __aenter__(self) -> MagicMock:
        return MagicMock()

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakePool:
    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire()


@pytest.mark.asyncio
async def test_resync_meta_records_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = MagicMock()
    settings.meta_system_user_token = "tok"
    monkeypatch.setattr(meta_resync, "get_settings", lambda: settings)
    monkeypatch.setattr(
        meta_resync, "_fetch_all_adaccounts", AsyncMock(return_value=[{"id": "act_1", "name": "X"}])
    )
    monkeypatch.setattr(meta_resync.meta_ad_accounts, "upsert_many", AsyncMock(return_value=1))
    monkeypatch.setattr(meta_resync.connection, "get_pool", lambda: _FakePool())
    rec = AsyncMock(return_value=7)
    monkeypatch.setattr(meta_resync, "record_job_run", rec)

    n = await meta_resync.resync_meta()

    assert n == 1
    kwargs = rec.call_args.kwargs
    assert kwargs["operation"] == "meta_resync"
    assert kwargs["platform"] == "meta"
    assert kwargs["target_count"] == 1
