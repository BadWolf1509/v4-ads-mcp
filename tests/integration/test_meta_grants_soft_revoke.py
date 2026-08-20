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

        # I2 (fix round 1): reconceder pelo bulk_grant precisa acionar o ON
        # CONFLICT e restaurar — este e o unico teste da suite onde bulk_grant
        # roda sobre uma linha JA revogada (em _cenario a linha nao existe
        # ainda, entao o INSERT puro nunca colide).
        await manager_meta_account_access.bulk_grant(
            conn, manager_id=mid, ad_account_ids=["act_1"], granted_by=mid
        )
        assert await manager_meta_account_access.can_manager_access(conn, mid, "act_1") is True


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


@pytest.mark.integration
async def test_copy_access_nao_ressuscita_grant_revogado(db) -> None:
    """C1 (fix round 1): copiar de um gestor com grant revogado (mas conta
    ainda is_active — o JOIN de can_manager_access sozinho nao salva aqui) nao
    pode dar acesso VIVO ao destino. Era o bug: DELETE+INSERT sem filtro
    ressuscitava a linha revogada porque o INSERT nunca grava revoked_at."""
    async with db.acquire() as conn:
        origem = await _cenario(conn)
        destino = uuid4()
        await managers.create(conn, manager_id=destino, email="d@v4company.com", full_name=None)

        await manager_meta_account_access.revoke(
            conn, manager_id=origem, ad_account_id="act_1", reason="offboarding_origem"
        )

        n = await manager_meta_account_access.copy_access(
            conn, from_manager_id=origem, to_manager_id=destino, granted_by=origem
        )

        assert n == 0
        assert await manager_meta_account_access.can_manager_access(conn, destino, "act_1") is False
        assert await manager_meta_account_access.list_accounts_for_manager(conn, destino) == []


@pytest.mark.integration
async def test_copy_access_nao_apaga_historico_de_revogacao_do_destino(db) -> None:
    """C1 (fix round 1): copy_access era DELETE no destino — apagava o proprio
    rastro de revogacao que este commit inteiro existe pra preservar. Agora
    'substituir' e soft-revoke, entao uma linha JA revogada no destino (por
    outro motivo, antes desta chamada) tem que sobreviver intacta."""
    async with db.acquire() as conn:
        origem = await _cenario(conn)
        destino = uuid4()
        await managers.create(conn, manager_id=destino, email="d2@v4company.com", full_name=None)
        await meta_ad_accounts.upsert_many(
            conn,
            [
                {
                    "ad_account_id": "act_9",
                    "business_id": "bm",
                    "business_name": "BM",
                    "account_name": "Conta 9",
                    "currency": "BRL",
                    "timezone_name": "America/Sao_Paulo",
                    "account_status": 1,
                }
            ],
        )
        await manager_meta_account_access.grant(conn, manager_id=destino, ad_account_id="act_9")
        await manager_meta_account_access.revoke(
            conn, manager_id=destino, ad_account_id="act_9", reason="offboarding_destino"
        )

        await manager_meta_account_access.copy_access(
            conn, from_manager_id=origem, to_manager_id=destino, granted_by=origem
        )

        linha = await conn.fetchrow(
            "SELECT revoked_at, revoked_reason FROM manager_meta_account_access "
            "WHERE manager_id = $1 AND ad_account_id = 'act_9'",
            destino,
        )
        assert linha is not None, "copy_access apagou a linha revogada do destino"
        assert linha["revoked_at"] is not None
        assert linha["revoked_reason"] == "offboarding_destino"


@pytest.mark.integration
async def test_restaurar_so_devolve_quem_o_churn_revogou(db) -> None:
    """I4 (fix round 2): restore_for_account desfaz SO o que
    revoke_for_account revogou quando a parceria saiu — nao pode devolver
    acesso que um admin tirou por outro motivo (manual, copy_access, etc.) so
    porque a MESMA conta reapareceu na parceria depois."""
    async with db.acquire() as conn:
        mid_churn = await _cenario(conn)
        mid_manual = uuid4()
        await managers.create(conn, manager_id=mid_manual, email="m2@v4company.com", full_name=None)
        await manager_meta_account_access.bulk_grant(
            conn, manager_id=mid_manual, ad_account_ids=["act_1"], granted_by=mid_manual
        )

        # Revoga mid_manual primeiro, por outro motivo. revoke_for_account (a
        # seguir) so pega quem ainda esta VIVO (revoked_at IS NULL), entao
        # esta linha ja revogada sobrevive intacta com a razao "manual".
        await manager_meta_account_access.revoke(
            conn, manager_id=mid_manual, ad_account_id="act_1", reason="manual"
        )
        await manager_meta_account_access.revoke_for_account(
            conn, ad_account_id="act_1", reason="partnership_ended"
        )

        n = await manager_meta_account_access.restore_for_account(conn, ad_account_id="act_1")

        assert n == 1
        assert (
            await manager_meta_account_access.can_manager_access(conn, mid_churn, "act_1") is True
        )
        assert (
            await manager_meta_account_access.can_manager_access(conn, mid_manual, "act_1") is False
        )
