"""F128: `bulk_grant` e `grant_all_active` esqueciam `access_level` no `ON CONFLICT`.

`grant` (linha única) já fazia `access_level = EXCLUDED.access_level` ao
reconceder; `bulk_grant` e `grant_all_active` só limpavam `revoked_at`/
`revoked_reason` — quem já tinha 'read' continuava com 'read' depois de um
"conceder tudo" (por lista de customer_ids ou por toda conta ativa), sem erro
nenhum. É o F128 na forma canônica: cláusula presente num gêmeo (`grant`),
ausente nos outros dois. Terceira instância idêntica, byte a byte, no gêmeo
Meta (`manager_meta_account_access.bulk_grant`) — coberta em
`test_manager_meta_account_access.py`, não aqui.
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


@pytest.mark.integration
async def test_grant_all_active_promove_read_para_write(db) -> None:
    """F128: `grant_all_active` concede 'write' a toda conta ativa — inclusive
    a quem já tinha 'read'.

    Mesmo defeito do `bulk_grant` acima, na segunda instância: sem
    `access_level = EXCLUDED.access_level` no ON CONFLICT, a linha existente é
    preservada com o nível antigo. `grant_all_active` grava 'write' como
    literal no INSERT (não um parâmetro) — este teste também confirma que
    `EXCLUDED.access_level` resolve para esse literal, e não só para valores
    passados via parâmetro (caso do `bulk_grant`).
    """
    async with db.acquire() as conn:
        manager_id = await _make_manager(conn, "grant-all@v4company.com")
        await _make_account(conn, "3333333333")
        await manager_account_access.grant(
            conn,
            manager_id=manager_id,
            customer_id="3333333333",
            access_level="read",
            granted_by=manager_id,
        )

        await manager_account_access.grant_all_active(conn, manager_id=manager_id)

        nivel = await conn.fetchval(
            "SELECT access_level FROM manager_account_access "
            " WHERE manager_id = $1 AND customer_id = $2",
            manager_id,
            "3333333333",
        )
        assert nivel == "write", (
            "grant_all_active concede 'write', mas a linha que ja existia ficou em "
            f"{nivel!r} — o ON CONFLICT nao seta access_level (F128)"
        )


@pytest.mark.integration
async def test_grant_all_active_continua_limpando_a_revogacao(db) -> None:
    """Contraprova: o comportamento que o ON CONFLICT já tinha não regride."""
    async with db.acquire() as conn:
        manager_id = await _make_manager(conn, "grant-all2@v4company.com")
        await _make_account(conn, "4444444444")
        await manager_account_access.grant(
            conn,
            manager_id=manager_id,
            customer_id="4444444444",
            access_level="write",
            granted_by=manager_id,
        )
        await manager_account_access.revoke(
            conn, manager_id=manager_id, customer_id="4444444444", reason="teste"
        )

        await manager_account_access.grant_all_active(conn, manager_id=manager_id)

        linha = await conn.fetchrow(
            "SELECT access_level, revoked_at FROM manager_account_access "
            " WHERE manager_id = $1 AND customer_id = $2",
            manager_id,
            "4444444444",
        )
        assert linha["revoked_at"] is None, "a revogacao deveria ter sido limpa"
        assert linha["access_level"] == "write"
