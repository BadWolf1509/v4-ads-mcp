from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.google_ads import access
from src.google_ads.access import AccountAccessDeniedError


@pytest.mark.asyncio
async def test_ensure_account_access_allows_when_granted():
    conn = AsyncMock()
    with patch(
        "src.google_ads.access.manager_account_access.can_manager_access",
        AsyncMock(return_value=True),
    ):
        await access.ensure_account_access(
            conn,
            manager_id=uuid4(),
            customer_id="123",
            session_id=uuid4(),
            operation_name="get_campaign_performance",
            level="read",
        )


@pytest.mark.asyncio
async def test_ensure_account_access_denies_and_audits():
    conn = AsyncMock()
    mid, sid = uuid4(), uuid4()
    with (
        patch(
            "src.google_ads.access.manager_account_access.can_manager_access",
            AsyncMock(return_value=False),
        ),
        patch("src.google_ads.access.audit_log.record", AsyncMock()) as rec,
    ):
        with pytest.raises(AccountAccessDeniedError):
            await access.ensure_account_access(
                conn,
                manager_id=mid,
                customer_id="999",
                session_id=sid,
                operation_name="update_campaign_status",
                level="write",
            )
        rec.assert_awaited_once()
        kwargs = rec.await_args.kwargs
        assert kwargs["status"] == "denied"
        assert kwargs["customer_id"] == "999"
        assert kwargs["platform"] == "google"


@pytest.mark.asyncio
async def test_ensure_account_access_denial_message_conta_ativa_sem_grant():
    """Item 2 da revisão final: conta existe e está ATIVA, só falta grant —
    "peça ao admin pra liberar no painel" é o remédio certo aqui (a conta
    aparece na matriz e um grant novo resolve), então a mensagem tem que
    continuar a mesma de sempre.
    """
    conn = AsyncMock()
    with (
        patch(
            "src.google_ads.access.manager_account_access.can_manager_access",
            AsyncMock(return_value=False),
        ),
        patch("src.google_ads.access.audit_log.record", AsyncMock()),
        patch(
            "src.google_ads.access.google_ads_accounts.get_by_customer_id",
            AsyncMock(return_value=SimpleNamespace(is_active=True)),
        ),
        pytest.raises(AccountAccessDeniedError) as exc_info,
    ):
        await access.ensure_account_access(
            conn,
            manager_id=uuid4(),
            customer_id="1112223330",
            session_id=uuid4(),
            operation_name="op",
        )
    assert "Peça ao admin pra liberar no painel" in exc_info.value.message
    assert "MCC" not in exc_info.value.message


@pytest.mark.asyncio
async def test_ensure_account_access_denial_message_conta_ausente_ou_inativa():
    """Item 2 da revisão final: conta ausente do inventário OU is_active=false
    — "peça ao admin pra liberar no painel" não pode funcionar: a conta nem
    aparece na matriz (`list_all` só lista ativas) e o gate nega por
    `is_active` mesmo com um grant novo. A mensagem tem que apontar o caminho
    real (a conta voltar ao MCC + o resync rodar), não o painel.
    """
    conn = AsyncMock()
    for conta_simulada in (None, SimpleNamespace(is_active=False)):
        with (
            patch(
                "src.google_ads.access.manager_account_access.can_manager_access",
                AsyncMock(return_value=False),
            ),
            patch("src.google_ads.access.audit_log.record", AsyncMock()),
            patch(
                "src.google_ads.access.google_ads_accounts.get_by_customer_id",
                AsyncMock(return_value=conta_simulada),
            ),
            pytest.raises(AccountAccessDeniedError) as exc_info,
        ):
            await access.ensure_account_access(
                conn,
                manager_id=uuid4(),
                customer_id="4445556660",
                session_id=uuid4(),
                operation_name="op",
            )
        assert "não está no MCC" in exc_info.value.message
        assert "Peça ao admin pra liberar no painel" not in exc_info.value.message
