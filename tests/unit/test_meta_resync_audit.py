"""reconcile_meta() grava 1 audit_log de job (operation=meta_reconcile, platform=meta).

Historicamente este arquivo também cobria `_deactivate_churned` (deteccao de
churn agrupada por business_id via `mark_inactive_except`) — mecanismo
aposentado na Task 7 (2026-08-20), substituido por `build_plan()` +
`meta_ad_accounts.deactivate()`. O teste que provava aquele comportamento saiu
junto (não há mais call-site pra provar); a propriedade que sobrevive — o job
grava UMA linha de audit com operation/platform/target_count corretos —
continua coberta abaixo, contra `reconcile_meta()`.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.auth.meta_oauth import AdAccountsFetch
from src.jobs import meta_resync
from src.meta_ads.partnership import PartnershipSnapshot


class _FakeAcquire:
    async def __aenter__(self) -> MagicMock:
        conn = MagicMock()
        # A transacao do bloco de apply (Req. 1) precisa de um `conn` que
        # suporte `async with conn.transaction():` — MagicMock ja suporta
        # __aenter__/__aexit__ magicos por padrao, sem setup extra.
        conn.execute = AsyncMock(return_value="UPDATE 0")
        return conn

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakePool:
    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire()


@pytest.mark.asyncio
async def test_reconcile_meta_records_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = MagicMock()
    settings.meta_system_user_token = "tok"
    settings.meta_business_id = "bm"
    settings.meta_reconcile_apply = False
    monkeypatch.setattr(meta_resync, "get_settings", lambda: settings)
    monkeypatch.setattr(
        meta_resync,
        "fetch_partnership",
        AsyncMock(
            return_value=PartnershipSnapshot(
                [{"ad_account_id": "act_1", "account_name": "X"}], True
            )
        ),
    )
    monkeypatch.setattr(
        meta_resync,
        "_fetch_all_adaccounts",
        AsyncMock(return_value=AdAccountsFetch(accounts=[{"id": "act_1"}], complete=True)),
    )
    monkeypatch.setattr(meta_resync.meta_ad_accounts, "upsert_many", AsyncMock(return_value=1))
    monkeypatch.setattr(
        meta_resync.meta_ad_accounts, "list_inventory_rows", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(meta_resync.connection, "get_pool", lambda: _FakePool())
    rec = AsyncMock(return_value=7)
    monkeypatch.setattr(meta_resync, "record_job_run", rec)

    plano = await meta_resync.reconcile_meta()

    # Inventario vazio + parceria com act_1 → build_plan() propoe adicionar.
    assert plano.to_add == ["act_1"]
    kwargs = rec.call_args.kwargs
    assert kwargs["operation"] == "meta_reconcile"
    assert kwargs["platform"] == "meta"
    assert kwargs["target_count"] == 1
    assert kwargs["status"] == "success"
