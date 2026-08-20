"""Revogar precisa ser reversivel e auditavel — o grant e curadoria humana.

E o gate precisa negar SEM depender do reconciliador ter rodado: sob token de
system user, ele e a unica fronteira que sobra (confused deputy).
"""

from uuid import uuid4

import pytest

from src.db.repositories import manager_meta_account_access, managers, meta_ad_accounts

CONTA = {
    "ad_account_id": "act_1",
    "business_id": "bm",
    "business_name": "BM",
    "account_name": "Conta 1",
    "currency": "BRL",
    "timezone_name": "America/Sao_Paulo",
    "account_status": 1,
}


async def _cenario(conn):
    mid = uuid4()
    await managers.create(conn, manager_id=mid, email="g@v4company.com", full_name=None)
    await meta_ad_accounts.upsert_many(conn, [CONTA])
    await manager_meta_account_access.bulk_grant(
        conn, manager_id=mid, ad_account_ids=["act_1"], granted_by=mid
    )
    return mid


@pytest.mark.integration
async def test_revogacao_preserva_a_linha_e_o_motivo(db) -> None:
    async with db.acquire() as conn:
        mid = await _cenario(conn)

        atingidos = await manager_meta_account_access.revoke_for_account(
            conn, ad_account_id="act_1", reason="partnership_ended"
        )

        assert atingidos == [mid]
        linha = await conn.fetchrow(
            "SELECT revoked_at, revoked_reason FROM manager_meta_account_access "
            "WHERE manager_id = $1 AND ad_account_id = 'act_1'",
            mid,
        )
        assert linha["revoked_at"] is not None
        assert linha["revoked_reason"] == "partnership_ended"


@pytest.mark.integration
async def test_grant_revogado_nao_da_acesso_nem_aparece_na_lista(db) -> None:
    async with db.acquire() as conn:
        mid = await _cenario(conn)
        await manager_meta_account_access.revoke_for_account(
            conn, ad_account_id="act_1", reason="partnership_ended"
        )

        assert await manager_meta_account_access.can_manager_access(conn, mid, "act_1") is False
        assert await manager_meta_account_access.list_accounts_for_manager(conn, mid) == []


@pytest.mark.integration
async def test_restaurar_devolve_exatamente_quem_tinha(db) -> None:
    async with db.acquire() as conn:
        mid = await _cenario(conn)
        await manager_meta_account_access.revoke_for_account(
            conn, ad_account_id="act_1", reason="partnership_ended"
        )

        n = await manager_meta_account_access.restore_for_account(conn, ad_account_id="act_1")

        assert n == 1
        assert await manager_meta_account_access.can_manager_access(conn, mid, "act_1") is True


@pytest.mark.integration
async def test_gate_nega_conta_desativada_mesmo_com_grant_vivo(db) -> None:
    """Defesa em profundidade: se o reconciliador atrasar, o gate ja nega."""
    async with db.acquire() as conn:
        mid = await _cenario(conn)
        await meta_ad_accounts.deactivate(conn, ad_account_ids=["act_1"])

        assert await manager_meta_account_access.can_manager_access(conn, mid, "act_1") is False
