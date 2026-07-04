"""Testes de orquestração do job src/jobs/backup.py (run()).

run() é o Cloud Run Job semanal: descobre tabelas via information_schema,
faz dump csv.gz de cada uma (asyncpg COPY em memória) e sobe pro bucket GCS
(settings.backup_bucket). Mockamos TODAS as dependências externas (pool,
storage.Client, record_job_run) e asseveramos: iteração das tabelas
descobertas, blob names `<data>/<tbl>.csv.gz`, 1x upload_from_string por
tabela, e o audit gravado com operation="db_backup". Nada bate no GCS real.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from freezegun import freeze_time

from src.jobs import backup

_M = "src.jobs.backup"


def _fake_pool(conn: MagicMock) -> MagicMock:
    """Pool mock cujo acquire() é um async context manager que devolve `conn`."""
    pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield conn

    pool.acquire = _acquire
    return pool


def _fake_conn(tables: list[str]) -> MagicMock:
    """Connection mock: fetch() devolve as tabelas; copy_from_query grava algo no sink."""
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=[{"table_name": t} for t in tables])

    async def _copy_from_query(query, *, output, format, header):  # noqa: A002
        await output(b"col_a,col_b\r\nval1,val2\r\n")
        return "COPY 1"

    conn.copy_from_query = AsyncMock(side_effect=_copy_from_query)
    return conn


def _base_patches(*, pool: MagicMock, storage_client: MagicMock, record_return: int = 1):
    return {
        "init_pool": patch(f"{_M}.connection.init_pool", AsyncMock()),
        "close_pool": patch(f"{_M}.connection.close_pool", AsyncMock()),
        "get_pool": patch(f"{_M}.connection.get_pool", MagicMock(return_value=pool)),
        "storage_client": patch(f"{_M}.storage.Client", MagicMock(return_value=storage_client)),
        "record": patch(f"{_M}.record_job_run", AsyncMock(return_value=record_return)),
    }


def _fake_storage_client() -> tuple[MagicMock, dict[str, MagicMock]]:
    """storage.Client() fake: bucket() retorna um bucket mock cujo blob() retorna um
    blob mock por blob_name (dict compartilhado pra assert em upload_from_string)."""
    blobs: dict[str, MagicMock] = {}

    def _blob(name: str) -> MagicMock:
        b = blobs.setdefault(name, MagicMock())
        return b

    bucket = MagicMock()
    bucket.blob = MagicMock(side_effect=_blob)
    client = MagicMock()
    client.bucket = MagicMock(return_value=bucket)
    return client, blobs


@freeze_time("2026-07-04")
@pytest.mark.asyncio
async def test_run_uploads_one_blob_per_table_and_records_audit() -> None:
    tables = ["_migrations", "audit_log", "managers"]
    conn = _fake_conn(tables)
    pool = _fake_pool(conn)
    client, blobs = _fake_storage_client()
    mocks = _base_patches(pool=pool, storage_client=client)

    with (
        mocks["init_pool"],
        mocks["close_pool"] as close_pool,
        mocks["get_pool"],
        mocks["storage_client"],
        mocks["record"] as record,
    ):
        rc = await backup.run()

    assert rc == 0
    close_pool.assert_awaited_once()

    # Um blob por tabela, nome exatamente <date_prefix>/<tbl>.csv.gz.
    assert set(blobs.keys()) == {
        "2026-07-04/_migrations.csv.gz",
        "2026-07-04/audit_log.csv.gz",
        "2026-07-04/managers.csv.gz",
    }
    for b in blobs.values():
        b.upload_from_string.assert_called_once()
        args, kwargs = b.upload_from_string.call_args
        assert kwargs["content_type"] == "application/gzip"
        assert isinstance(args[0], bytes)

    record.assert_awaited_once()
    kwargs = record.call_args.kwargs
    assert kwargs["operation"] == "db_backup"
    assert kwargs["platform"] == "google"
    assert kwargs["target_count"] == 3
    assert kwargs["status"] == "success"
    assert kwargs["params_summary"]["tables"] == tables
    assert kwargs["params_summary"]["bucket"] == "v4-ads-mcp-backups"
    assert kwargs["params_summary"]["total_bytes"] > 0


@freeze_time("2026-07-04")
@pytest.mark.asyncio
async def test_run_discovers_tables_via_information_schema() -> None:
    """A query de descoberta filtra public + BASE TABLE e ordena por nome."""
    conn = _fake_conn(["zzz_table", "aaa_table"])
    pool = _fake_pool(conn)
    client, _ = _fake_storage_client()
    mocks = _base_patches(pool=pool, storage_client=client)

    with (
        mocks["init_pool"],
        mocks["close_pool"],
        mocks["get_pool"],
        mocks["storage_client"],
        mocks["record"],
    ):
        await backup.run()

    sql = conn.fetch.call_args.args[0]
    assert "information_schema.tables" in sql
    assert "table_schema = 'public'" in sql
    assert "table_type = 'BASE TABLE'" in sql
    assert "ORDER BY table_name" in sql


@freeze_time("2026-07-04")
@pytest.mark.asyncio
async def test_run_continues_after_one_table_fails_and_returns_1() -> None:
    """Uma tabela falhando não aborta as demais, mas o exit code final é 1 (alerta)."""
    tables = ["ok_table", "broken_table", "another_ok_table"]
    conn = _fake_conn(tables)

    call_count = {"n": 0}
    orig_copy = conn.copy_from_query

    async def _copy_with_failure(query, *, output, format, header):  # noqa: A002
        call_count["n"] += 1
        if "broken_table" in query:
            raise RuntimeError("boom")
        return await orig_copy(query, output=output, format=format, header=header)

    conn.copy_from_query = AsyncMock(side_effect=_copy_with_failure)
    pool = _fake_pool(conn)
    client, blobs = _fake_storage_client()
    mocks = _base_patches(pool=pool, storage_client=client)

    with (
        mocks["init_pool"],
        mocks["close_pool"],
        mocks["get_pool"],
        mocks["storage_client"],
        mocks["record"] as record,
    ):
        rc = await backup.run()

    assert rc == 1
    # As 3 tabelas foram tentadas (não abortou no meio).
    assert call_count["n"] == 3
    # Só as 2 boas viraram blob.
    assert set(blobs.keys()) == {
        "2026-07-04/ok_table.csv.gz",
        "2026-07-04/another_ok_table.csv.gz",
    }
    kwargs = record.call_args.kwargs
    assert kwargs["status"] == "error"
    assert kwargs["target_count"] == 2
    assert kwargs["params_summary"]["failed_tables"] == ["broken_table"]
    assert kwargs["error_message"]


@pytest.mark.asyncio
async def test_run_closes_pool_even_when_discovery_fails() -> None:
    """close_pool() no finally roda mesmo se a descoberta de tabelas explodir."""
    conn = MagicMock()
    conn.fetch = AsyncMock(side_effect=RuntimeError("db down"))
    pool = _fake_pool(conn)
    client, _ = _fake_storage_client()
    mocks = _base_patches(pool=pool, storage_client=client)

    with (
        mocks["init_pool"],
        mocks["close_pool"] as close_pool,
        mocks["get_pool"],
        mocks["storage_client"],
        mocks["record"],
        pytest.raises(RuntimeError, match="db down"),
    ):
        await backup.run()

    close_pool.assert_awaited_once()


def test_main_wraps_run_in_asyncio_run() -> None:
    """main() delega pra asyncio.run(run()) e propaga o exit code."""
    with (
        patch(f"{_M}.run", MagicMock(return_value="sentinel-coro")),
        patch(f"{_M}.asyncio.run", MagicMock(return_value=0)) as asyncio_run,
    ):
        rc = backup.main()

    assert rc == 0
    asyncio_run.assert_called_once_with("sentinel-coro")
