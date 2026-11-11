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

import asyncpg
import pytest

from src.db.repositories import google_ads_accounts, manager_account_access
from tests.integration._seed import seed_manager


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
        manager_id = await seed_manager(conn, email="bulk@v4company.com")
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
        manager_id = await seed_manager(conn, email="bulk2@v4company.com")
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
        manager_id = await seed_manager(conn, email="grant-all@v4company.com")
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
        manager_id = await seed_manager(conn, email="grant-all2@v4company.com")
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


# --- G0 (decisão de 10/11): re-conceder registra quem e quando ----------------


async def _carimbar_antigo(conn, manager_id, customer_id: str, quem) -> None:
    """Põe `granted_at`/`granted_by` num estado reconhecível, no passado."""
    await conn.execute(
        "UPDATE manager_account_access SET granted_at = '2020-01-01T00:00:00+00:00', "
        "       granted_by = $3 "
        " WHERE manager_id = $1 AND customer_id = $2",
        manager_id,
        customer_id,
        quem,
    )


async def _procedencia(conn, manager_id, customer_id: str):
    return await conn.fetchrow(
        "SELECT granted_at, granted_by, revoked_at FROM manager_account_access "
        " WHERE manager_id = $1 AND customer_id = $2",
        manager_id,
        customer_id,
    )


@pytest.mark.integration
@pytest.mark.parametrize("revogar", [True, False], ids=["revogada", "ativa"])
async def test_grant_all_active_reconceder_atualiza_granted_at_e_by(db, revogar: bool) -> None:
    """G0: "Atualizar sempre" — re-concessão (linha revogada OU ativa) carimba
    `granted_at = now()` e `granted_by` de quem concedeu agora."""
    async with db.acquire() as conn:
        gestor = await seed_manager(conn, email=f"ga-g0-{revogar}@v4company.com")
        antigo = await seed_manager(conn, email=f"ga-g0-antigo-{revogar}@v4company.com")
        novo = await seed_manager(conn, email=f"ga-g0-novo-{revogar}@v4company.com")
        await _make_account(conn, "5555555555")
        await manager_account_access.grant(
            conn, manager_id=gestor, customer_id="5555555555", granted_by=antigo
        )
        await _carimbar_antigo(conn, gestor, "5555555555", antigo)
        if revogar:
            await manager_account_access.revoke(conn, manager_id=gestor, customer_id="5555555555")

        await manager_account_access.grant_all_active(conn, manager_id=gestor, granted_by=novo)

        linha = await _procedencia(conn, gestor, "5555555555")
        assert linha["revoked_at"] is None
        assert linha["granted_by"] == novo, "granted_by nao foi atualizado na re-concessao"
        assert linha["granted_at"].year > 2020, "granted_at nao foi atualizado na re-concessao"


@pytest.mark.integration
@pytest.mark.parametrize("revogar", [True, False], ids=["revogada", "ativa"])
async def test_bulk_grant_reconceder_atualiza_granted_at_e_by(db, revogar: bool) -> None:
    """G0: o mesmo para `bulk_grant` (Google)."""
    async with db.acquire() as conn:
        gestor = await seed_manager(conn, email=f"bg-g0-{revogar}@v4company.com")
        antigo = await seed_manager(conn, email=f"bg-g0-antigo-{revogar}@v4company.com")
        novo = await seed_manager(conn, email=f"bg-g0-novo-{revogar}@v4company.com")
        await _make_account(conn, "6666666666")
        await manager_account_access.grant(
            conn, manager_id=gestor, customer_id="6666666666", granted_by=antigo
        )
        await _carimbar_antigo(conn, gestor, "6666666666", antigo)
        if revogar:
            await manager_account_access.revoke(conn, manager_id=gestor, customer_id="6666666666")

        await manager_account_access.bulk_grant(
            conn, manager_id=gestor, customer_ids=["6666666666"], granted_by=novo
        )

        linha = await _procedencia(conn, gestor, "6666666666")
        assert linha["revoked_at"] is None
        assert linha["granted_by"] == novo, "granted_by nao foi atualizado na re-concessao"
        assert linha["granted_at"].year > 2020, "granted_at nao foi atualizado na re-concessao"
