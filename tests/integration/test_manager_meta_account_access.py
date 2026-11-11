"""F128: o `bulk_grant` (gêmeo Meta) esquecia `access_level` no `ON CONFLICT`.

Mesmo defeito do lado Google, terceira instância nesta PR (ver
`test_manager_account_access.py`, que cobre as outras duas —
`manager_account_access.bulk_grant` e `.grant_all_active`): `grant` (linha
única) já fazia `access_level = EXCLUDED.access_level` ao reconceder;
`bulk_grant` só limpava `revoked_at`/`revoked_reason` — quem já tinha 'read'
continuava com 'read' depois de um "conceder tudo", sem erro nenhum. É o F128
na forma canônica: cláusula presente num gêmeo (`grant`, e no `bulk_grant`
Google já corrigido), ausente aqui.
"""

import asyncpg
import pytest

from src.db.repositories import manager_meta_account_access, meta_ad_accounts
from tests.integration._seed import seed_manager


async def _make_account(conn: asyncpg.Connection, ad_account_id: str) -> None:
    """Create a meta_ad_accounts row — manager_meta_account_access.ad_account_id
    references it (mesmo motivo do gêmeo Google: FK real)."""
    await meta_ad_accounts.upsert_many(
        conn,
        [{"ad_account_id": ad_account_id, "business_id": "bm_test", "account_name": "Test"}],
    )


@pytest.mark.integration
async def test_bulk_grant_promove_read_para_write(db) -> None:
    """F128: o `bulk_grant` concede 'write' — inclusive a quem já tinha 'read'.

    Sem `access_level = EXCLUDED.access_level` no ON CONFLICT, a linha existente
    é preservada com o nível antigo. O gestor pede "conceder tudo", a tool
    responde sucesso, e o acesso continua somente-leitura — em silêncio, que é
    a parte cara.
    """
    async with db.acquire() as conn:
        manager_id = await seed_manager(conn, email="mbulk@v4company.com")
        await _make_account(conn, "act_1111111111")
        await manager_meta_account_access.grant(
            conn,
            manager_id=manager_id,
            ad_account_id="act_1111111111",
            access_level="read",
            granted_by=manager_id,
        )

        await manager_meta_account_access.bulk_grant(
            conn,
            manager_id=manager_id,
            ad_account_ids=["act_1111111111"],
            granted_by=manager_id,
        )

        nivel = await conn.fetchval(
            "SELECT access_level FROM manager_meta_account_access "
            " WHERE manager_id = $1 AND ad_account_id = $2",
            manager_id,
            "act_1111111111",
        )
        assert nivel == "write", (
            "bulk_grant concede 'write', mas a linha que ja existia ficou em "
            f"{nivel!r} — o ON CONFLICT nao seta access_level (F128)"
        )


@pytest.mark.integration
async def test_bulk_grant_continua_limpando_a_revogacao(db) -> None:
    """Contraprova: o comportamento que o ON CONFLICT já tinha não regride."""
    async with db.acquire() as conn:
        manager_id = await seed_manager(conn, email="mbulk2@v4company.com")
        await _make_account(conn, "act_2222222222")
        await manager_meta_account_access.grant(
            conn,
            manager_id=manager_id,
            ad_account_id="act_2222222222",
            access_level="write",
            granted_by=manager_id,
        )
        await manager_meta_account_access.revoke(
            conn, manager_id=manager_id, ad_account_id="act_2222222222", reason="teste"
        )

        await manager_meta_account_access.bulk_grant(
            conn,
            manager_id=manager_id,
            ad_account_ids=["act_2222222222"],
            granted_by=manager_id,
        )

        linha = await conn.fetchrow(
            "SELECT access_level, revoked_at FROM manager_meta_account_access "
            " WHERE manager_id = $1 AND ad_account_id = $2",
            manager_id,
            "act_2222222222",
        )
        assert linha["revoked_at"] is None, "a revogacao deveria ter sido limpa"
        assert linha["access_level"] == "write"


@pytest.mark.integration
async def test_revogar_de_novo_nao_tira_a_linha_do_restore(db) -> None:
    """Spec 2026-09-28 §3.2.1: o `revoke` manual só pega linha viva.

    Sem `AND revoked_at IS NULL`, revogar de novo uma linha que o churn já revogou
    re-carimba o motivo: `partnership_ended` vira `manual`, e o `restore_for_account` —
    que filtra por esse motivo — deixa de devolver o acesso quando a parceria volta.
    """
    async with db.acquire() as conn:
        manager_id = await seed_manager(conn, email="mrevoga2x@v4company.com")
        await _make_account(conn, "act_3333333333")
        await manager_meta_account_access.grant(
            conn,
            manager_id=manager_id,
            ad_account_id="act_3333333333",
            access_level="write",
            granted_by=manager_id,
        )
        await manager_meta_account_access.revoke_for_account(
            conn,
            ad_account_id="act_3333333333",
            reason=manager_meta_account_access.PARTNERSHIP_ENDED_REASON,
        )

        await manager_meta_account_access.revoke(
            conn, manager_id=manager_id, ad_account_id="act_3333333333", reason="manual"
        )

        motivo = await conn.fetchval(
            "SELECT revoked_reason FROM manager_meta_account_access "
            " WHERE manager_id = $1 AND ad_account_id = $2",
            manager_id,
            "act_3333333333",
        )
        assert motivo == manager_meta_account_access.PARTNERSHIP_ENDED_REASON
        restauradas = await manager_meta_account_access.restore_for_account(
            conn, ad_account_id="act_3333333333"
        )
        assert restauradas == 1


# --- G0 (decisão de 10/11): re-conceder registra quem e quando; motivo unificado --


@pytest.mark.integration
@pytest.mark.parametrize("revogar", [True, False], ids=["revogada", "ativa"])
async def test_bulk_grant_reconceder_atualiza_granted_at_e_by(db, revogar: bool) -> None:
    """G0: "Atualizar sempre" — re-concessão (linha revogada OU ativa) carimba
    `granted_at = now()` e `granted_by` de quem concedeu agora."""
    async with db.acquire() as conn:
        gestor = await seed_manager(conn, email=f"mbg-g0-{revogar}@v4company.com")
        antigo = await seed_manager(conn, email=f"mbg-g0-antigo-{revogar}@v4company.com")
        novo = await seed_manager(conn, email=f"mbg-g0-novo-{revogar}@v4company.com")
        await _make_account(conn, "act_4444444444")
        await manager_meta_account_access.grant(
            conn, manager_id=gestor, ad_account_id="act_4444444444", granted_by=antigo
        )
        await conn.execute(
            "UPDATE manager_meta_account_access SET granted_at = '2020-01-01T00:00:00+00:00'::timestamptz "
            " WHERE manager_id = $1 AND ad_account_id = $2",
            gestor,
            "act_4444444444",
        )
        if revogar:
            await manager_meta_account_access.revoke(
                conn, manager_id=gestor, ad_account_id="act_4444444444"
            )

        await manager_meta_account_access.bulk_grant(
            conn, manager_id=gestor, ad_account_ids=["act_4444444444"], granted_by=novo
        )

        linha = await conn.fetchrow(
            "SELECT granted_at, granted_by, revoked_at FROM manager_meta_account_access "
            " WHERE manager_id = $1 AND ad_account_id = $2",
            gestor,
            "act_4444444444",
        )
        assert linha["revoked_at"] is None
        assert linha["granted_by"] == novo, "granted_by nao foi atualizado na re-concessao"
        assert linha["granted_at"].year > 2020, "granted_at nao foi atualizado na re-concessao"


@pytest.mark.integration
async def test_revoke_sem_motivo_grava_admin_revoked(db) -> None:
    """G0: motivo unificado — `revoke` Meta sem motivo explícito grava o mesmo
    `admin_revoked` do Google (era `manual`)."""
    async with db.acquire() as conn:
        gestor = await seed_manager(conn, email="mrev-g0@v4company.com")
        await _make_account(conn, "act_5555555555")
        await manager_meta_account_access.grant(
            conn, manager_id=gestor, ad_account_id="act_5555555555", granted_by=gestor
        )

        await manager_meta_account_access.revoke(
            conn, manager_id=gestor, ad_account_id="act_5555555555"
        )

        motivo = await conn.fetchval(
            "SELECT revoked_reason FROM manager_meta_account_access "
            " WHERE manager_id = $1 AND ad_account_id = $2",
            gestor,
            "act_5555555555",
        )
        assert motivo == "admin_revoked"
