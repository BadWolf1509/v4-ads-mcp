"""Testes de orquestração do job src/jobs/account_resync.py (run()/main()).

run() é o Cloud Run Job diário: escolhe uma OAuth connection, decifra o refresh token,
builda o client, descobre customers, puxa detalhes, faz upsert + mark_inactive, grava
audit (record_job_run) e faz piggyback do resync Meta. Mockamos TODAS as dependências
(build client, repos, resync_meta, connection pool) e asseveramos a orquestração +
exit codes: 1 sem OAuth connection, 0 no sucesso, chama record_job_run, Meta é best-effort.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.jobs import account_resync

_M = "src.jobs.account_resync"


def _fake_pool(conn: MagicMock) -> MagicMock:
    """Pool mock cujo acquire() é um async context manager que devolve `conn`."""
    pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield conn

    pool.acquire = _acquire
    return pool


def _base_patches(
    *,
    pool: MagicMock,
    oc: object,
    manager: object = None,
    accounts: list | None = None,
    resource_names: list | None = None,
    upsert_return: int = 3,
    deactivated_return: int = 1,
):
    """Contextmanager-stack comum dos testes. Retorna dict de mocks pra assert."""
    accounts = (
        accounts
        if accounts is not None
        else [
            {"customer_id": "1111111111"},
            {"customer_id": "2222222222"},
        ]
    )
    resource_names = resource_names if resource_names is not None else ["customers/6436352492"]

    mocks = {
        "init_pool": patch(f"{_M}.connection.init_pool", AsyncMock()),
        "close_pool": patch(f"{_M}.connection.close_pool", AsyncMock()),
        "get_pool": patch(f"{_M}.connection.get_pool", MagicMock(return_value=pool)),
        "pick": patch(f"{_M}._pick_oauth_connection", AsyncMock(return_value=(manager, oc))),
        "derive": patch(f"{_M}.derive_master_key_from_settings", MagicMock(return_value=b"k" * 32)),
        "decrypt": patch(f"{_M}.decrypt_refresh_token", MagicMock(return_value="refresh-tok")),
        "build_client": patch(f"{_M}.build_client", MagicMock(return_value=MagicMock())),
        "list_customers": patch(
            f"{_M}.list_accessible_customer_resource_names",
            MagicMock(return_value=resource_names),
        ),
        "fetch": patch(f"{_M}.fetch_account_details", MagicMock(return_value=accounts)),
        "upsert": patch(
            f"{_M}.google_ads_accounts.upsert_many", AsyncMock(return_value=upsert_return)
        ),
        "mark_inactive": patch(
            f"{_M}.google_ads_accounts.mark_inactive_except",
            AsyncMock(return_value=deactivated_return),
        ),
        "record": patch(f"{_M}.record_job_run", AsyncMock(return_value=1)),
    }
    return mocks


@pytest.mark.asyncio
async def test_run_returns_1_when_no_oauth_connection() -> None:
    """Sem OAuth connection ativa → early return 1 (nada de client/upsert)."""
    conn = MagicMock()
    pool = _fake_pool(conn)
    mocks = _base_patches(pool=pool, oc=None)

    with (
        mocks["init_pool"],
        mocks["close_pool"] as close_pool,
        mocks["get_pool"],
        mocks["pick"],
        mocks["build_client"] as build_client,
        mocks["upsert"] as upsert,
    ):
        rc = await account_resync.run()

    assert rc == 1
    build_client.assert_not_called()
    upsert.assert_not_awaited()
    # pool sempre fechado no finally.
    close_pool.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_happy_path_returns_0_and_orchestrates() -> None:
    conn = MagicMock()
    pool = _fake_pool(conn)
    oc = SimpleNamespace(refresh_token_enc=b"enc")
    mocks = _base_patches(pool=pool, oc=oc, upsert_return=2, deactivated_return=1)

    with (
        mocks["init_pool"],
        mocks["close_pool"] as close_pool,
        mocks["get_pool"],
        mocks["pick"],
        mocks["derive"],
        mocks["decrypt"] as decrypt,
        mocks["build_client"] as build_client,
        mocks["list_customers"] as list_customers,
        mocks["fetch"] as fetch,
        mocks["upsert"] as upsert,
        mocks["mark_inactive"] as mark_inactive,
        mocks["record"] as record,
        patch("src.jobs.meta_resync.resync_meta", AsyncMock(return_value=7)),
    ):
        rc = await account_resync.run()

    assert rc == 0
    decrypt.assert_called_once()
    build_client.assert_called_once()
    list_customers.assert_called_once()
    fetch.assert_called_once()
    upsert.assert_awaited_once()
    mark_inactive.assert_awaited_once()
    record.assert_awaited_once()
    close_pool.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_records_job_run_with_operation_and_deactivated_count() -> None:
    conn = MagicMock()
    pool = _fake_pool(conn)
    oc = SimpleNamespace(refresh_token_enc=b"enc")
    mocks = _base_patches(pool=pool, oc=oc, upsert_return=2, deactivated_return=5)

    with (
        mocks["init_pool"],
        mocks["close_pool"],
        mocks["get_pool"],
        mocks["pick"],
        mocks["derive"],
        mocks["decrypt"],
        mocks["build_client"],
        mocks["list_customers"],
        mocks["fetch"],
        mocks["upsert"],
        mocks["mark_inactive"],
        mocks["record"] as record,
        patch("src.jobs.meta_resync.resync_meta", AsyncMock(return_value=0)),
    ):
        await account_resync.run()

    kwargs = record.call_args.kwargs
    assert kwargs["operation"] == "account_resync"
    assert kwargs["platform"] == "google"
    assert kwargs["target_count"] == 2
    assert kwargs["params_summary"] == {"deactivated": 5}


@pytest.mark.asyncio
async def test_run_passes_keep_ids_to_mark_inactive() -> None:
    conn = MagicMock()
    pool = _fake_pool(conn)
    oc = SimpleNamespace(refresh_token_enc=b"enc")
    accounts = [{"customer_id": "111"}, {"customer_id": "222"}, {"customer_id": "333"}]
    mocks = _base_patches(pool=pool, oc=oc, accounts=accounts)

    with (
        mocks["init_pool"],
        mocks["close_pool"],
        mocks["get_pool"],
        mocks["pick"],
        mocks["derive"],
        mocks["decrypt"],
        mocks["build_client"],
        mocks["list_customers"],
        mocks["fetch"],
        mocks["upsert"],
        mocks["mark_inactive"] as mark_inactive,
        mocks["record"],
        patch("src.jobs.meta_resync.resync_meta", AsyncMock(return_value=0)),
    ):
        await account_resync.run()

    kwargs = mark_inactive.call_args.kwargs
    assert kwargs["keep_customer_ids"] == ["111", "222", "333"]


@pytest.mark.asyncio
async def test_run_meta_failure_is_non_fatal() -> None:
    """Piggyback do Meta explode → run() ainda retorna 0 (best-effort, não quebra Google)."""
    conn = MagicMock()
    pool = _fake_pool(conn)
    oc = SimpleNamespace(refresh_token_enc=b"enc")
    mocks = _base_patches(pool=pool, oc=oc)

    with (
        mocks["init_pool"],
        mocks["close_pool"] as close_pool,
        mocks["get_pool"],
        mocks["pick"],
        mocks["derive"],
        mocks["decrypt"],
        mocks["build_client"],
        mocks["list_customers"],
        mocks["fetch"],
        mocks["upsert"],
        mocks["mark_inactive"],
        mocks["record"],
        patch("src.jobs.meta_resync.resync_meta", AsyncMock(side_effect=RuntimeError("meta down"))),
    ):
        rc = await account_resync.run()

    assert rc == 0
    close_pool.assert_awaited_once()


def test_main_wraps_run_in_asyncio_run() -> None:
    """main() delega pra asyncio.run(run()) e propaga o exit code.

    `run` é patchado com MagicMock (não AsyncMock) de propósito: main() só passa
    run() como argumento pra asyncio.run — que aqui é mockado e NÃO awaita. Um
    AsyncMock deixaria uma coroutine órfã (RuntimeWarning: never awaited).
    """
    with (
        patch(f"{_M}.run", MagicMock(return_value="sentinel-coro")),
        patch(f"{_M}.asyncio.run", MagicMock(return_value=0)) as asyncio_run,
    ):
        rc = account_resync.main()

    assert rc == 0
    asyncio_run.assert_called_once_with("sentinel-coro")
