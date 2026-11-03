"""`pick_admin_active`: a escolha da conexão OAuth do job de resync é determinística."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import asyncpg
import pytest

from src.db.repositories import google_oauth_connections, managers

_MOMENTO = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


async def _admin(conn: asyncpg.Connection, email: str, *, com_oauth: bool = True) -> UUID:
    mid = uuid4()
    await managers.create(conn, manager_id=mid, email=email, full_name=email, role="admin")
    # Mesmo created_at nos dois: só o desempate por id separa os candidatos.
    await conn.execute("UPDATE managers SET created_at = $2 WHERE id = $1", mid, _MOMENTO)
    if com_oauth:
        await google_oauth_connections.upsert(
            conn,
            manager_id=mid,
            google_email=email,
            refresh_token_enc=b"x",
            scopes=["adwords"],
        )
    return mid


@pytest.mark.integration
async def test_dois_admins_ativos_escolhem_sempre_o_mesmo(db) -> None:
    pool = db
    async with pool.acquire() as conn:
        a = await _admin(conn, "admin-a@v4.com")
        b = await _admin(conn, "admin-b@v4.com")
        esperado = min(a, b)  # created_at empata: o menor id vence

        escolhas = [await google_oauth_connections.pick_admin_active(conn) for _ in range(5)]

    assert all(e is not None for e in escolhas)
    assert {e.manager_id for e in escolhas if e} == {esperado}


@pytest.mark.integration
async def test_admin_sem_oauth_ativo_e_pulado(db) -> None:
    pool = db
    async with pool.acquire() as conn:
        await _admin(conn, "sem-oauth@v4.com", com_oauth=False)
        com = await _admin(conn, "com-oauth@v4.com")

        escolhida = await google_oauth_connections.pick_admin_active(conn)

    assert escolhida is not None
    assert escolhida.manager_id == com


@pytest.mark.integration
async def test_sem_admin_com_oauth_devolve_none(db) -> None:
    pool = db
    async with pool.acquire() as conn:
        assert await google_oauth_connections.pick_admin_active(conn) is None
