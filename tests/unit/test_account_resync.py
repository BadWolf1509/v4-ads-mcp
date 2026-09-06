"""Testes de orquestração do job src/jobs/account_resync.py (run()/main()).

run() é o Cloud Run Job diário: escolhe uma OAuth connection, decifra o refresh token,
builda o client, descobre customers, puxa detalhes, chama reconcile_google (upsert +
carência + deactivate/revoke atrás da trava), grava audit (record_job_run), faz
piggyback da reconciliação Meta e purga tabelas transientes (purge_expired). Mockamos
TODAS as dependências (build client, reconcile_google, reconcile_meta, purge_expired,
connection pool) e asseveramos a orquestração + exit codes: 1 sem OAuth connection
(auditado como status='error'), 0 no sucesso, chama record_job_run, Meta e purge são
best-effort.

`reconcile_google` (Task 5) é mockado por INTEIRO, igual `reconcile_meta` — este
arquivo prova a ORQUESTRAÇÃO de `run()` (accounts/complete/apply chegam certos,
resumo vira params_summary certo), não a lógica de reconciliação em si. Essa lógica
(carência, build_plan, o guard de inventário vazio) tem cobertura própria contra
banco real em tests/integration/test_repositories.py — mockar `reconcile_google`
aqui e reler `test_repositories.py` lá é o que evita um teste "verde" que não prova
mais nada depois que o job parou de chamar `mark_inactive_except` diretamente.

O piggyback (`src.jobs.meta_resync.reconcile_meta`) é mockado devolvendo um `Plan`
vazio de propósito: nenhum teste aqui inspeciona o conteúdo do plano — só que o
piggyback foi chamado e que uma falha nele não derruba o resync do Google.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.jobs import account_resync
from src.meta_ads.reconcile import Plan

_M = "src.jobs.account_resync"


def _reconcile_result(**overrides: Any) -> dict[str, Any]:
    """Formato devolvido por `reconcile_google` (Task 5) — default 'nada mudou'."""
    base: dict[str, Any] = {
        "added": 0,
        "bumped": 0,
        "removed": 0,
        "reset": 0,
        "revoke_candidates": 0,
        "revoked_grants": 0,
        "applied": False,
        "complete": True,
        "upserted": 0,
        "blocked_reason": None,
    }
    base.update(overrides)
    return base


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
    reconcile_result: dict[str, Any] | None = None,
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
    reconcile_result = (
        reconcile_result
        if reconcile_result is not None
        else _reconcile_result(upserted=len(accounts))
    )

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
        # Task 5: substitui os antigos mocks de `upsert_many`/`mark_inactive_except`
        # — o job não chama mais nenhum dos dois diretamente, e continuar mockando
        # funções que a produção não invoca mais provaria zero (era exatamente o
        # risco apontado na revisão: guard vácuo).
        "reconcile_google": patch(
            f"{_M}.reconcile_google", AsyncMock(return_value=reconcile_result)
        ),
        "record": patch(f"{_M}.record_job_run", AsyncMock(return_value=1)),
        # Task 7: mockado por INTEIRO, igual `reconcile_google` — a lógica
        # própria (lê `list_queues`, só loga quando há o que avisar) tem
        # cobertura contra banco real em tests/integration/test_repositories.py.
        # Sem este mock, `conn` (MagicMock puro) faz `list_queues` explodir.
        "avisar_sem_grant": patch(f"{_M}.avisar_contas_sem_grant", AsyncMock(return_value=0)),
        "purge": patch(
            f"{_M}.purge_expired",
            AsyncMock(
                return_value={
                    "pending_confirmations": 0,
                    "rate_counters": 0,
                    "meta_rate_counters": 0,
                }
            ),
        ),
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
        mocks["reconcile_google"] as reconcile_google,
        mocks["record"] as record,
    ):
        rc = await account_resync.run()

    assert rc == 1
    build_client.assert_not_called()
    reconcile_google.assert_not_awaited()
    # pool sempre fechado no finally.
    close_pool.assert_awaited_once()

    # F73: falha de OAuth deve ficar visível no /audit — status='error'.
    record.assert_awaited_once()
    kwargs = record.call_args.kwargs
    # I2 (revisão de branch, 2026-09-05): unificado com o caminho de
    # sucesso/bloqueio e com o crash do except externo — os três gravavam
    # `operation` diferente ("account_resync" aqui e no crash, "google_reconcile"
    # no sucesso), e a query de triagem do soak filtra por UMA string só.
    assert kwargs["operation"] == "google_reconcile"
    assert kwargs["status"] == "error"
    assert kwargs["error_message"]


@pytest.mark.asyncio
async def test_run_happy_path_returns_0_and_orchestrates() -> None:
    conn = MagicMock()
    pool = _fake_pool(conn)
    oc = SimpleNamespace(refresh_token_enc=b"enc")
    mocks = _base_patches(
        pool=pool, oc=oc, reconcile_result=_reconcile_result(upserted=2, removed=1)
    )

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
        mocks["reconcile_google"] as reconcile_google,
        mocks["avisar_sem_grant"] as avisar_sem_grant,
        mocks["record"] as record,
        mocks["purge"] as purge,
        patch("src.jobs.meta_resync.reconcile_meta", AsyncMock(return_value=Plan())),
    ):
        rc = await account_resync.run()

    assert rc == 0
    decrypt.assert_called_once()
    build_client.assert_called_once()
    list_customers.assert_called_once()
    fetch.assert_called_once()
    reconcile_google.assert_awaited_once()
    # record_job_run é chamado 2x no happy path: google_reconcile + db_purge (F73).
    assert record.await_count == 2
    purge.assert_awaited_once()
    # Task 7: chamado na MESMA conexão do reconcile (reusa o `conn` já
    # reconciliado nesta execução, não um acquire novo) — se `run()` parasse
    # de chamar `avisar_contas_sem_grant`, este mock ficaria sem uso e só esta
    # asserção pegaria (o mock em si não quebra nada quando não-chamado).
    avisar_sem_grant.assert_awaited_once_with(conn)
    close_pool.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_records_job_run_with_operation_and_reconcile_summary() -> None:
    """O resumo de `reconcile_google` vira `params_summary`; upserted/blocked_reason
    saem de lá porque já viram target_count/status/error_message — duplicá-los
    dentro do summary não acrescentaria nada pra quem lê o audit.
    """
    conn = MagicMock()
    pool = _fake_pool(conn)
    oc = SimpleNamespace(refresh_token_enc=b"enc")
    resumo = _reconcile_result(
        added=1,
        removed=2,
        reset=1,
        revoke_candidates=3,
        revoked_grants=2,
        applied=True,
        upserted=2,
    )
    mocks = _base_patches(pool=pool, oc=oc, reconcile_result=resumo)

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
        mocks["reconcile_google"],
        mocks["avisar_sem_grant"],
        mocks["record"] as record,
        mocks["purge"],
        patch("src.jobs.meta_resync.reconcile_meta", AsyncMock(return_value=Plan())),
    ):
        await account_resync.run()

    # 1ª chamada é a do reconcile propriamente dito (a 2ª, db_purge, é
    # coberta em test_run_calls_purge_expired_and_records_db_purge abaixo).
    kwargs = record.await_args_list[0].kwargs
    assert kwargs["operation"] == "google_reconcile"
    assert kwargs["platform"] == "google"
    assert kwargs["target_count"] == 2
    assert kwargs["status"] == "success"
    assert kwargs["error_message"] is None
    assert kwargs["params_summary"] == {
        "added": 1,
        "bumped": 0,
        "removed": 2,
        "reset": 1,
        "revoke_candidates": 3,
        "revoked_grants": 2,
        "applied": True,
        "complete": True,
    }


@pytest.mark.asyncio
async def test_run_passes_fetched_accounts_and_inventory_ok_to_reconcile_google() -> None:
    """`run()` repassa os `accounts` que buscou e `complete=inventario_ok` —
    é esta fiação que faz inventário vazio virar `complete=False` dentro de
    `reconcile_google` (o guard em si é testado contra banco real em
    tests/integration/test_repositories.py).
    """
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
        mocks["reconcile_google"] as reconcile_google,
        mocks["avisar_sem_grant"],
        mocks["record"],
        mocks["purge"],
        patch("src.jobs.meta_resync.reconcile_meta", AsyncMock(return_value=Plan())),
    ):
        await account_resync.run()

    kwargs = reconcile_google.call_args.kwargs
    assert kwargs["accounts"] == accounts
    assert kwargs["complete"] is True  # inventario_ok = bool(accounts)


@pytest.mark.asyncio
async def test_run_passes_google_reconcile_apply_setting_through() -> None:
    """A trava de rollout chega em `reconcile_google` como `apply=` — sem
    override de env ela é `False` (default de `Settings.google_reconcile_apply`).
    """
    conn = MagicMock()
    pool = _fake_pool(conn)
    oc = SimpleNamespace(refresh_token_enc=b"enc")
    mocks = _base_patches(pool=pool, oc=oc)

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
        mocks["reconcile_google"] as reconcile_google,
        mocks["avisar_sem_grant"],
        mocks["record"],
        mocks["purge"],
        patch("src.jobs.meta_resync.reconcile_meta", AsyncMock(return_value=Plan())),
    ):
        await account_resync.run()

    assert reconcile_google.call_args.kwargs["apply"] is False

    conn2 = MagicMock()
    pool2 = _fake_pool(conn2)
    mocks2 = _base_patches(pool=pool2, oc=oc)
    with (
        patch.dict("os.environ", {"GOOGLE_RECONCILE_APPLY": "true"}),
        mocks2["init_pool"],
        mocks2["close_pool"],
        mocks2["get_pool"],
        mocks2["pick"],
        mocks2["derive"],
        mocks2["decrypt"],
        mocks2["build_client"],
        mocks2["list_customers"],
        mocks2["fetch"],
        mocks2["reconcile_google"] as reconcile_google2,
        mocks2["avisar_sem_grant"],
        mocks2["record"],
        mocks2["purge"],
        patch("src.jobs.meta_resync.reconcile_meta", AsyncMock(return_value=Plan())),
    ):
        await account_resync.run()

    assert reconcile_google2.call_args.kwargs["apply"] is True


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
        mocks["reconcile_google"],
        mocks["avisar_sem_grant"],
        mocks["record"],
        mocks["purge"],
        patch(
            "src.jobs.meta_resync.reconcile_meta",
            AsyncMock(side_effect=RuntimeError("meta down")),
        ),
    ):
        rc = await account_resync.run()

    assert rc == 0
    close_pool.assert_awaited_once()


@pytest.mark.asyncio
async def test_falha_do_piggyback_meta_deixa_rastro_no_audit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """I2 (revisão de branch): este é o ÚNICO caminho que roda em produção.

    `record_job_crash` vivia só dentro de `meta_resync.run()`, alcançável apenas
    por `python -m src.jobs.meta_resync`. O Cloud Run Job diário chama
    `reconcile_meta()` daqui, e o `except` engolia tudo com um WARN — uma
    reconciliação quebrada há dias não deixava NENHUMA linha no `audit_log`, nem
    `status=error`. É a mesma classe do F93, na rota que de fato executa.
    """
    conn = MagicMock()
    pool = _fake_pool(conn)
    oc = SimpleNamespace(refresh_token_enc=b"enc")
    mocks = _base_patches(pool=pool, oc=oc)
    boom = RuntimeError("client_ad_accounts mudou de permissao")

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
        mocks["reconcile_google"],
        mocks["avisar_sem_grant"],
        mocks["record"],
        mocks["purge"],
        patch("src.jobs.meta_resync.reconcile_meta", AsyncMock(side_effect=boom)),
        patch(f"{_M}.record_job_crash", AsyncMock()) as crash,
    ):
        rc = await account_resync.run()

    assert rc == 0, "auditar o crash nao pode tornar o piggyback fatal"
    crash.assert_awaited_once()
    kwargs = crash.await_args.kwargs
    assert kwargs["operation"] == "meta_reconcile"
    assert kwargs["platform"] == "meta"
    assert kwargs["exc"] is boom
    # A falha original continua visível mesmo com a auditoria no caminho — o
    # audit OBSERVA o crash, não o substitui.
    assert "client_ad_accounts mudou de permissao" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_crash_inesperado_no_corpo_do_job_audita_como_google_reconcile() -> None:
    """I2 (revisão de branch): o `except` EXTERNO — que cobre build_client,
    fetch_account_details, reconcile_google e qualquer outra explosão no corpo
    do job — gravava `operation="account_resync"`, string DIFERENTE da que o
    caminho de sucesso/bloqueio grava (`google_reconcile`, ~:223). Igual ao
    "sem OAuth connection" (teste acima): pra job diário atrás de trava, é o
    dia em que o job MORREU que interessa, e uma query de triagem que filtra
    por `operation='google_reconcile'` fazia esse dia sumir da série — ausência
    virava indistinguível de "rodou e não achou nada". Unificado com o gêmeo
    Meta, que usa `meta_reconcile` nos dois casos (sucesso e crash).

    Diferente do teste do piggyback Meta (best-effort, `rc == 0`): este crash é
    no corpo do PRÓPRIO job Google — `run()` re-levanta depois de auditar.
    """
    conn = MagicMock()
    pool = _fake_pool(conn)
    oc = SimpleNamespace(refresh_token_enc=b"enc")
    mocks = _base_patches(pool=pool, oc=oc)
    boom = RuntimeError("build_client explodiu")

    with (
        mocks["init_pool"],
        mocks["close_pool"] as close_pool,
        mocks["get_pool"],
        mocks["pick"],
        mocks["derive"],
        mocks["decrypt"],
        patch(f"{_M}.build_client", MagicMock(side_effect=boom)),
        patch(f"{_M}.record_job_crash", AsyncMock()) as crash,
        pytest.raises(RuntimeError, match="build_client explodiu"),
    ):
        await account_resync.run()

    crash.assert_awaited_once()
    kwargs = crash.await_args.kwargs
    assert kwargs["operation"] == "google_reconcile"
    assert kwargs["platform"] == "google"
    assert kwargs["exc"] is boom
    # finally fecha o pool mesmo quando o except externo re-levanta.
    close_pool.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_calls_purge_expired_and_records_db_purge() -> None:
    """purge_expired() é chamado no fim do job e o resultado é auditado como db_purge."""
    conn = MagicMock()
    pool = _fake_pool(conn)
    oc = SimpleNamespace(refresh_token_enc=b"enc")
    mocks = _base_patches(pool=pool, oc=oc)
    counts = {"pending_confirmations": 12, "rate_counters": 3, "meta_rate_counters": 1}

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
        mocks["reconcile_google"],
        mocks["avisar_sem_grant"],
        mocks["record"] as record,
        patch(f"{_M}.purge_expired", AsyncMock(return_value=counts)) as purge,
        patch("src.jobs.meta_resync.reconcile_meta", AsyncMock(return_value=Plan())),
    ):
        rc = await account_resync.run()

    assert rc == 0
    purge.assert_awaited_once_with(pool)
    db_purge_kwargs = record.await_args_list[-1].kwargs
    assert db_purge_kwargs["operation"] == "db_purge"
    assert db_purge_kwargs["platform"] == "google"
    assert db_purge_kwargs["target_count"] == 16
    assert db_purge_kwargs["params_summary"] == counts


@pytest.mark.asyncio
async def test_run_purge_failure_is_non_fatal() -> None:
    """purge_expired() explode → run() ainda retorna 0 (best-effort, não quebra o resync)."""
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
        mocks["reconcile_google"],
        mocks["avisar_sem_grant"],
        mocks["record"],
        patch(f"{_M}.purge_expired", AsyncMock(side_effect=RuntimeError("db down"))),
        patch("src.jobs.meta_resync.reconcile_meta", AsyncMock(return_value=Plan())),
    ):
        rc = await account_resync.run()

    assert rc == 0
    close_pool.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_avisar_sem_grant_failure_is_non_fatal() -> None:
    """avisar_contas_sem_grant() explode → run() ainda retorna 0, e o piggyback
    Meta + o purge diário (que vêm DEPOIS no código) continuam rodando —
    isolado no mesmo padrão dos dois vizinhos. Espelha
    `test_run_meta_failure_is_non_fatal` e `test_run_purge_failure_is_non_fatal`.

    Antes do isolamento (revisão de branch, 2026-09-05), esta falha escapava
    do `async with pool.acquire()` e pulava INTEIRAMENTE o piggyback Meta e o
    purge — os dois asserts de `assert_awaited_once()` abaixo são o que
    fica vermelho sem o try/except novo. `crash.assert_not_awaited()` cobre
    a outra metade do achado: sem isolar, a exceção caía no `except` externo
    e gravava um SEGUNDO `record_job_run` como crash logo depois do sucesso
    já commitado — duas linhas de auditoria contraditórias pra mesma
    execução.
    """
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
        mocks["reconcile_google"],
        patch(
            f"{_M}.avisar_contas_sem_grant",
            AsyncMock(side_effect=RuntimeError("list_queues down")),
        ),
        mocks["record"],
        mocks["purge"] as purge,
        patch(f"{_M}.record_job_crash", AsyncMock()) as crash,
        patch(
            "src.jobs.meta_resync.reconcile_meta", AsyncMock(return_value=Plan())
        ) as reconcile_meta,
    ):
        rc = await account_resync.run()

    assert rc == 0
    close_pool.assert_awaited_once()
    reconcile_meta.assert_awaited_once()
    purge.assert_awaited_once()
    crash.assert_not_awaited()


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
