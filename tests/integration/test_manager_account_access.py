"""F128: o `bulk_grant` esquecia `access_level` no `ON CONFLICT`.

`grant` (linha única) já fazia `access_level = EXCLUDED.access_level` ao
reconceder; `bulk_grant` só limpava `revoked_at`/`revoked_reason` — quem já
tinha 'read' continuava com 'read' depois de um "conceder tudo", sem erro
nenhum. É o F128 na forma canônica: cláusula presente num gêmeo (`grant`),
ausente no outro (`bulk_grant`). Mesmo bug, byte a byte, no gêmeo Meta
(`manager_meta_account_access.bulk_grant`) — fora do escopo desta suíte.
"""

from uuid import UUID, uuid4

import asyncpg
import pytest

from src.db.repositories import google_ads_accounts, manager_account_access, managers


async def _make_manager(conn: asyncpg.Connection, email: str) -> UUID:
    """Shared helper: create a manager row with a fresh id, return the id."""
    mid = uuid4()
    await managers.create(conn, manager_id=mid, email=email, full_name=None)
    return mid


async def _make_account(conn: asyncpg.Connection, customer_id: str) -> None:
    """Create a google_ads_accounts row — manager_account_access.customer_id has a real FK."""
    await google_ads_accounts.upsert_many(
        conn,
        [{"customer_id": customer_id, "mcc_id": "6436352492", "descriptive_name": "Test"}],
    )


@pytest.mark.integration
async def test_bulk_grant_promove_read_para_write(db) -> None:
    """F128: o `bulk_grant` concede 'write' — inclusive a quem ja tinha 'read'.

    Sem `access_level = EXCLUDED.access_level` no ON CONFLICT, a linha existente
    e preservada com o nivel antigo. O gestor pede "conceder tudo", a tool
    responde sucesso, e o acesso continua somente-leitura — em silencio, que e
    a parte cara.
    """
    async with db.acquire() as conn:
        manager_id = await _make_manager(conn, "bulk@v4company.com")
        await _make_account(conn, "1111111111")
        await manager_account_access.grant(
            conn,
            manager_id=manager_id,
            customer_id="1111111111",
            access_level="read",
            granted_by=manager_id,
        )

        await manager_account_access.bulk_grant(
            conn,
            manager_id=manager_id,
            customer_ids=["1111111111"],
            granted_by=manager_id,
        )

        nivel = await conn.fetchval(
            "SELECT access_level FROM manager_account_access "
            " WHERE manager_id = $1 AND customer_id = $2",
            manager_id,
            "1111111111",
        )
        assert nivel == "write", (
            "bulk_grant concede 'write', mas a linha que ja existia ficou em "
            f"{nivel!r} — o ON CONFLICT nao seta access_level (F128)"
        )


@pytest.mark.integration
async def test_bulk_grant_continua_limpando_a_revogacao(db) -> None:
    """Contraprova: o comportamento que o ON CONFLICT ja tinha nao regride."""
    async with db.acquire() as conn:
        manager_id = await _make_manager(conn, "bulk2@v4company.com")
        await _make_account(conn, "2222222222")
        await manager_account_access.grant(
            conn,
            manager_id=manager_id,
            customer_id="2222222222",
            access_level="write",
            granted_by=manager_id,
        )
        await manager_account_access.revoke(
            conn, manager_id=manager_id, customer_id="2222222222", reason="teste"
        )

        await manager_account_access.bulk_grant(
            conn,
            manager_id=manager_id,
            customer_ids=["2222222222"],
            granted_by=manager_id,
        )

        linha = await conn.fetchrow(
            "SELECT access_level, revoked_at FROM manager_account_access "
            " WHERE manager_id = $1 AND customer_id = $2",
            manager_id,
            "2222222222",
        )
        assert linha["revoked_at"] is None, "a revogacao deveria ter sido limpa"
        assert linha["access_level"] == "write"
