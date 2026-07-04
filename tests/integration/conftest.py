"""Fixtures compartilhadas: 1 container Postgres por sessão + template database.

Migrations rodam UMA vez num template (tpl_app); cada teste recebe um banco
novo clonado via CREATE DATABASE ... TEMPLATE — isolamento total (os
customer_id hardcoded continuam válidos) sem pagar boot+migrations por teste.
"""

import asyncio
import itertools
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate

_SIGNING_KEY = "x" * 32
_AES_MASTER = "y" * 43
_TEMPLATE_DB = "tpl_app"
_seq = itertools.count()


def _dsn(container: PostgresContainer, dbname: str | None = None) -> str:
    # rsplit, NÃO .replace("/test", ...): user/senha também são "test"
    # (postgresql://test:test@...), replace corromperia o DSN.
    url = container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    return url if dbname is None else url.rsplit("/", 1)[0] + "/" + dbname


async def _prepare_template(admin_dsn: str, template_dsn: str) -> None:
    conn = await asyncpg.connect(admin_dsn)
    try:
        await conn.execute(f'CREATE DATABASE "{_TEMPLATE_DB}"')
    finally:
        await conn.close()
    # migrate.run_all() lê o pool global — aponta ele pro template, roda, fecha.
    # close_pool() garante ZERO conexões no template (exigência do TEMPLATE clone).
    await connection.init_pool(template_dsn, min_size=1, max_size=2)
    try:
        await migrate.run_all()
    finally:
        await connection.close_pool()


@pytest.fixture(scope="session")
def pg():
    # Fixture SYNC session-scoped. Instancia ANTES da autouse function-scoped
    # _test_env (escopo maior primeiro), então os defaults Docker do
    # tests/conftest.py ainda não foram aplicados — repita aqui.
    if sys.platform == "win32":
        os.environ.setdefault("DOCKER_HOST", "npipe:////./pipe/docker_engine")
        os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")
    container = PostgresContainer("postgres:16-alpine").with_command(
        "postgres -c fsync=off -c synchronous_commit=off -c full_page_writes=off"
    )
    with container:
        # asyncio.run: loop privado só do setup; nenhum objeto asyncpg sobrevive.
        asyncio.run(_prepare_template(_dsn(container), _dsn(container, _TEMPLATE_DB)))
        yield container


@asynccontextmanager
async def _clone_db(pg: PostgresContainer) -> AsyncIterator[str]:
    """Clona um banco novo do template; yields o DSN; DROP no cleanup.

    Compartilhado por `db` e `app_with_db` — ambos precisam do banco isolado,
    mas `app_with_db` também precisa do DSN cru pra setar DATABASE_URL via env
    (lido por get_settings() em código que roda depois do create_app()).
    """
    name = f"test_{os.getpid()}_{next(_seq)}"
    admin = await asyncpg.connect(_dsn(pg))
    try:
        await admin.execute(f'CREATE DATABASE "{name}" TEMPLATE "{_TEMPLATE_DB}"')
    finally:
        await admin.close()
    try:
        yield _dsn(pg, name)
    finally:
        admin = await asyncpg.connect(_dsn(pg))
        try:
            await admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        finally:
            await admin.close()


@pytest.fixture
async def db(pg):
    """Banco novo clonado do template; pool global aponta pra ele."""
    assert connection._pool is None, "pool global vazou do teste anterior"
    async with _clone_db(pg) as dsn:
        await connection.init_pool(dsn, min_size=1, max_size=4)
        try:
            yield connection.get_pool()
        finally:
            await connection.close_pool()


@pytest.fixture
async def app_with_db(pg, monkeypatch):
    """App com pool real inicializado num banco clonado do template."""
    assert connection._pool is None, "pool global vazou do teste anterior"
    async with _clone_db(pg) as dsn:
        monkeypatch.setenv("DATABASE_URL", dsn)
        monkeypatch.setenv("SESSION_SIGNING_KEY", _SIGNING_KEY)
        monkeypatch.setenv("AES_MASTER_KEY", _AES_MASTER)

        from src.app import (
            create_app,  # lazy import to avoid module-level create_app() before env is set
        )

        app = create_app(skip_db_init=True)
        await connection.init_pool(dsn, min_size=1, max_size=4)
        try:
            yield app
        finally:
            await connection.close_pool()


@pytest.fixture
async def client(app_with_db) -> AsyncClient:
    transport = ASGITransport(app=app_with_db)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
