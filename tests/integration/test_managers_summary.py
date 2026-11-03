"""Leituras de gestor usadas pelo painel de acesso: list_active e get_summary."""

from uuid import uuid4

import pytest

from src.db.repositories import managers


async def _insert(conn, email: str, *, active: bool, role: str = "gestor", name: str | None = None):
    mid = uuid4()
    await conn.execute(
        """INSERT INTO managers (id, email, full_name, role, status, is_active)
           VALUES ($1, $2, $3, $4, 'active', $5)""",
        mid,
        email,
        name,
        role,
        active,
    )
    return mid


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_active_filtra_inativos_e_ordena_por_email(db):
    async with db.acquire() as conn:
        await _insert(conn, "zeta@v4company.com", active=True, name="Zeta")
        await _insert(conn, "alfa@v4company.com", active=True, role="admin")
        await _insert(conn, "fora@v4company.com", active=False)
        rows = await managers.list_active(conn)

    assert [r["email"] for r in rows] == ["alfa@v4company.com", "zeta@v4company.com"]
    assert set(rows[0].keys()) == {"id", "email", "full_name", "role"}
    assert rows[0]["role"] == "admin"
    assert rows[1]["full_name"] == "Zeta"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_summary_devolve_campos_e_none_se_ausente(db):
    async with db.acquire() as conn:
        mid = await _insert(conn, "inativo@v4company.com", active=False, name="Inativo")
        row = await managers.get_summary(conn, mid)
        ausente = await managers.get_summary(conn, uuid4())

    assert row is not None
    assert set(row.keys()) == {"id", "email", "full_name"}
    assert row["id"] == mid
    assert row["email"] == "inativo@v4company.com"
    assert row["full_name"] == "Inativo"
    assert ausente is None
