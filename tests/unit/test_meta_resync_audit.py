"""resync_meta() grava 1 audit_log de job (operation=meta_resync, platform=meta)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.auth.meta_oauth import AdAccountsFetch
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
        meta_resync,
        "_fetch_all_adaccounts",
        AsyncMock(
            return_value=AdAccountsFetch(accounts=[{"id": "act_1", "name": "X"}], complete=True)
        ),
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


@pytest.mark.asyncio
async def test_resync_meta_deactivates_churned_per_business(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F65: mark_inactive_except é chamado UMA vez por business_id, com o keep-list
    só das contas daquele BM (nunca misturando BMs) e pulando contas sem business_id."""
    settings = MagicMock()
    settings.meta_system_user_token = "tok"
    monkeypatch.setattr(meta_resync, "get_settings", lambda: settings)
    # 2 BMs distintos + 1 conta pessoal (sem business) que deve ser ignorada.
    monkeypatch.setattr(
        meta_resync,
        "_fetch_all_adaccounts",
        AsyncMock(
            return_value=AdAccountsFetch(
                accounts=[
                    {"id": "act_1", "name": "A", "business": {"id": "bmX", "name": "BM X"}},
                    {"id": "act_2", "name": "B", "business": {"id": "bmX", "name": "BM X"}},
                    {"id": "act_3", "name": "C", "business": {"id": "bmY", "name": "BM Y"}},
                    {"id": "act_9", "name": "pessoal"},  # sem business → pulada
                ],
                complete=True,
            )
        ),
    )
    monkeypatch.setattr(meta_resync.meta_ad_accounts, "upsert_many", AsyncMock(return_value=4))
    monkeypatch.setattr(meta_resync, "record_job_run", AsyncMock(return_value=1))
    monkeypatch.setattr(meta_resync.connection, "get_pool", lambda: _FakePool())
    mie = AsyncMock(return_value=0)
    monkeypatch.setattr(meta_resync.meta_ad_accounts, "mark_inactive_except", mie)

    await meta_resync.resync_meta()

    # Uma chamada por business_id (2), nenhuma pra conta sem BM.
    calls = {c.kwargs["business_id"]: c.kwargs["keep_ad_account_ids"] for c in mie.call_args_list}
    assert set(calls) == {"bmX", "bmY"}
    assert sorted(calls["bmX"]) == ["act_1", "act_2"]
    assert calls["bmY"] == ["act_3"]
    # a conta pessoal (act_9) nunca aparece em nenhum keep-list
    assert all("act_9" not in keep for keep in calls.values())
