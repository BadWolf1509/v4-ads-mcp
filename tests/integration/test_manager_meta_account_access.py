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

from uuid import UUID, uuid4

import asyncpg
import pytest

from src.db.repositories import manager_meta_account_access, managers, meta_ad_accounts


async def _make_manager(conn: asyncpg.Connection, email: str) -> UUID:
    """Shared helper: create a manager row with a fresh id, return the id."""
    mid = uuid4()
    await managers.create(conn, manager_id=mid, email=email, full_name=None)
    return mid


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
        manager_id = await _make_manager(conn, "mbulk@v4company.com")
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
        manager_id = await _make_manager(conn, "mbulk2@v4company.com")
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
