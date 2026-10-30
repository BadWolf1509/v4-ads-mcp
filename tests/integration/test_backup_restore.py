"""Backup -> restore de ida e volta contra Postgres real (Task 4).

O runbook mandava `copy_to_table` sem `setval`: o COPY grava `id` explicito e
nao avanca a sequence do `audit_log`, entao o INSERT seguinte batia em
`UniqueViolationError (id)=(1)` — medido em Postgres 16. O dump tambem inclui
`_migrations`, que conflita com o schema ja migrado.
"""

import gzip
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

import asyncpg
import pytest

from src.db.repositories import audit_log
from src.jobs.backup import _dump_table_to_blob, _list_tables
from src.jobs.restore import ORDEM_RESTORE, restaurar_tabelas
from tests.integration.conftest import _clone_db


class _BlobEmDisco:
    """Faz o papel do blob do GCS: `open("wb")` grava num arquivo local."""

    def __init__(self, caminho: Path) -> None:
        self._caminho = caminho

    @contextmanager
    def open(self, modo: str, **_kw: Any):
        with self._caminho.open(modo) as f:
            yield f


async def _dump_tudo(conn: asyncpg.Connection, pasta: Path) -> None:
    for tabela in await _list_tables(conn):
        await _dump_table_to_blob(conn, tabela, _BlobEmDisco(pasta / f"{tabela}.csv.gz"))


async def _popular(conn: asyncpg.Connection, *, com_audit: bool) -> dict[str, int]:
    admin, gestor = uuid4(), uuid4()
    sessao = uuid4()
    await conn.execute(
        "INSERT INTO managers (id, email, status, role) VALUES ($1, 'ad@v4company.com', 'active', 'admin')",
        admin,
    )
    await conn.execute(
        "INSERT INTO managers (id, email, status, role, invited_by) "
        "VALUES ($1, 'ge@v4company.com', 'active', 'gestor', $2)",
        gestor,
        admin,
    )
    await conn.execute(
        "INSERT INTO google_oauth_connections (manager_id, google_email, refresh_token_enc, scopes) "
        "VALUES ($1, 'x@g.com', $2, ARRAY['a','b'])",
        gestor,
        b"\x00\xffsegredo\x10",
    )
    await conn.execute(
        "INSERT INTO google_ads_accounts (customer_id, mcc_id, descriptive_name) "
        "VALUES ('1111111111', '9', 'Conta')"
    )
    await conn.execute(
        "INSERT INTO manager_account_access (manager_id, customer_id, granted_by) "
        "VALUES ($1, '1111111111', $2)",
        gestor,
        admin,
    )
    await conn.execute(
        "INSERT INTO mcp_sessions (id, manager_id, token_hash) VALUES ($1, $2, 'h')",
        sessao,
        gestor,
    )
    await conn.execute(
        "INSERT INTO pending_confirmations (token, session_id, customer_id, operation_type, "
        "payload, blast_summary, expires_at) "
        "VALUES ('tok', $1, '1111111111', 'op', '{\"a\": 1}'::jsonb, 'b', now() + interval '1 hour')",
        sessao,
    )
    if com_audit:
        for i in range(3):
            await audit_log.record(
                conn,
                manager_id=gestor,
                session_id=sessao,
                customer_id="1111111111",
                action_type="read",
                operation=f"op{i}",
            )
    await conn.execute("INSERT INTO rate_counters (developer_token_id, date) VALUES ('t', now())")
    await conn.execute(
        "INSERT INTO meta_oauth_connections (manager_id, fb_user_id, fb_email, access_token_enc, "
        "token_expires_at, scopes) VALUES ($1, 'fb', 'f@f.com', $2, now(), ARRAY['s'])",
        gestor,
        b"\x01\x02",
    )
    await conn.execute(
        "INSERT INTO meta_ad_accounts (ad_account_id, account_name) VALUES ('act_1', 'M')"
    )
    await conn.execute(
        "INSERT INTO manager_meta_account_access (manager_id, ad_account_id) VALUES ($1, 'act_1')",
        gestor,
    )
    await conn.execute(
        "INSERT INTO meta_rate_counters (app_id, ad_account_id, date) VALUES ('a', 'act_1', now())"
    )
    return {t: await conn.fetchval(f'SELECT count(*) FROM "{t}"') for t in ORDEM_RESTORE}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_backup_e_restore_ida_e_volta(db, pg, tmp_path) -> None:
    async with db.acquire() as origem:
        esperado = await _popular(origem, com_audit=True)
        await _dump_tudo(origem, tmp_path)
        token_original = await origem.fetchval(
            "SELECT refresh_token_enc FROM google_oauth_connections"
        )

    assert (tmp_path / "_migrations.csv.gz").exists()  # o dump inclui; o restore pula

    async with _clone_db(pg) as dsn:
        destino = await asyncpg.connect(dsn)
        try:
            contagens = await restaurar_tabelas(destino, tmp_path)
            assert contagens == esperado
            for tabela, n in esperado.items():
                assert await destino.fetchval(f'SELECT count(*) FROM "{tabela}"') == n
            assert (
                await destino.fetchval("SELECT refresh_token_enc FROM google_oauth_connections")
                == token_original
            )
            # O ponto do Task 4: a sequence foi recolocada, o INSERT seguinte nao colide.
            novo = await audit_log.record(
                destino,
                manager_id=None,
                session_id=None,
                customer_id=None,
                action_type="system",
                operation="pos_restore",
            )
            assert novo == 4
        finally:
            await destino.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_restore_com_audit_vazio(db, pg, tmp_path) -> None:
    """Review Focus 5: tabela vazia -> setval(1, false); o 1o INSERT recebe id 1."""
    async with db.acquire() as origem:
        await _popular(origem, com_audit=False)
        assert await origem.fetchval("SELECT count(*) FROM audit_log") == 0
        await _dump_tudo(origem, tmp_path)

    async with _clone_db(pg) as dsn:
        destino = await asyncpg.connect(dsn)
        try:
            contagens = await restaurar_tabelas(destino, tmp_path)
            assert contagens["audit_log"] == 0
            novo = await audit_log.record(
                destino,
                manager_id=None,
                session_id=None,
                customer_id=None,
                action_type="system",
                operation="pos_restore",
            )
            assert novo == 1
        finally:
            await destino.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_restore_recusa_pasta_incompleta_antes_de_copiar(db, pg, tmp_path) -> None:
    async with db.acquire() as origem:
        await _popular(origem, com_audit=True)
        await _dump_tudo(origem, tmp_path)
    (tmp_path / "meta_rate_counters.csv.gz").unlink()

    async with _clone_db(pg) as dsn:
        destino = await asyncpg.connect(dsn)
        try:
            with pytest.raises(FileNotFoundError, match="meta_rate_counters"):
                await restaurar_tabelas(destino, tmp_path)
            assert await destino.fetchval("SELECT count(*) FROM managers") == 0
        finally:
            await destino.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_restore_recusa_tabela_desconhecida_na_pasta(db, pg, tmp_path) -> None:
    async with db.acquire() as origem:
        await _popular(origem, com_audit=False)
        await _dump_tudo(origem, tmp_path)
    with gzip.open(tmp_path / "tabela_nova.csv.gz", "wb") as f:
        f.write(b"a\n1\n")

    async with _clone_db(pg) as dsn:
        destino = await asyncpg.connect(dsn)
        try:
            with pytest.raises(ValueError, match="tabela_nova"):
                await restaurar_tabelas(destino, tmp_path)
        finally:
            await destino.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ordem_de_restore_cobre_todas_as_tabelas_do_schema(db) -> None:
    """Tabela nova numa migration sem entrar em ORDEM_RESTORE ficaria fora do restore."""
    async with db.acquire() as conn:
        tabelas = set(await _list_tables(conn)) - {"_migrations"}
    assert tabelas == set(ORDEM_RESTORE)
