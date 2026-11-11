"""F207: quatro falhas pré-existentes dos jobs em que o sinal não chegava a quem vigia.

Medido em 11/11 (`gcloud alpha monitoring policies list`): a única policy que
enxerga um Cloud Run Job é "Cloud Run Job: execucao FALHOU", keyed no exit code.
A policy `severity>=ERROR` é do SERVIÇO (`cloud_run_revision`), não do job. Então
o que não muda o exit code nem chega ao audit é invisível.

Padrão: desfecho observável — todo desfecho do job sai no exit code E no audit, e
a falha da operação fica separada da falha do bookkeeping (o mesmo corte do F83).
"""

from __future__ import annotations

from contextlib import ExitStack
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.jobs import _runner, account_resync
from src.meta_ads.reconcile import Plan
from tests.unit.fixtures.fake_pool import FakePool
from tests.unit.test_account_resync import _base_patches
from tests.unit.test_jobs_contrato_de_execucao import _entrar

_M = "src.jobs.account_resync"


def _so_o_db_purge_falha(*_a: Any, **kw: Any) -> int:
    if kw.get("operation") == "db_purge":
        raise RuntimeError("audit fora do ar")
    return 1


# --- 1. falha do purge muda o exit code e grava audit --------------------------------
@pytest.mark.asyncio
async def test_falha_do_purge_sai_com_1_e_grava_db_purge_como_erro() -> None:
    mocks = _base_patches(pool=FakePool(MagicMock()), oc=SimpleNamespace(refresh_token_enc=b"e"))
    with ExitStack() as stack:
        _entrar(stack, mocks, sem=("purge", "record"))
        stack.enter_context(
            patch(f"{_M}.purge_expired", AsyncMock(side_effect=RuntimeError("db down")))
        )
        stack.enter_context(
            patch("src.jobs.meta_resync.reconcile_meta", AsyncMock(return_value=Plan()))
        )
        record = stack.enter_context(patch(f"{_M}.record_job_run", AsyncMock(return_value=1)))
        crash = stack.enter_context(patch(f"{_M}.record_job_crash", AsyncMock()))
        rc = await account_resync.run()

    assert rc == 1, "falha do purge nao chega a policy de job falho"
    crash.assert_not_awaited()
    purges = [c.kwargs for c in record.await_args_list if c.kwargs["operation"] == "db_purge"]
    assert len(purges) == 1, "falha do purge nao deixou linha no audit"
    assert purges[0]["status"] == "error"
    assert "db down" in purges[0]["error_message"]


# --- 2. purge que apagou não é relatado como "purge falhou" ---------------------------
@pytest.mark.asyncio
async def test_purge_ok_com_audit_falhando_nao_diz_que_o_purge_falhou(
    capsys: pytest.CaptureFixture[str],
) -> None:
    mocks = _base_patches(pool=FakePool(MagicMock()), oc=SimpleNamespace(refresh_token_enc=b"e"))
    with ExitStack() as stack:
        _entrar(stack, mocks, sem=("record",))
        # Logger do modulo trocado, nao `capture_logs()`: o structlog e estado
        # global do processo pytest e o capture volta vazio conforme a ordem.
        log_bk = stack.enter_context(patch("src.governance.bookkeeping.log", MagicMock()))
        stack.enter_context(
            patch("src.jobs.meta_resync.reconcile_meta", AsyncMock(return_value=Plan()))
        )
        stack.enter_context(
            patch(f"{_M}.record_job_run", AsyncMock(side_effect=_so_o_db_purge_falha))
        )
        rc = await account_resync.run()

    saida = capsys.readouterr()
    assert rc == 0, "o purge apagou; so o audit dele falhou (bookkeeping, F83)"
    assert "purge falhou" not in saida.err
    assert "OK: purged" in saida.out
    eventos = [c.args[0] for c in log_bk.exception.call_args_list]
    assert "db_purge_audit_failed" in eventos, eventos


# --- 3. audit do "sem OAuth" que falha não vira crash ---------------------------------
@pytest.mark.asyncio
async def test_sem_oauth_com_audit_falhando_sai_com_1_sem_crash() -> None:
    mocks = _base_patches(pool=FakePool(MagicMock()), oc=None)
    with ExitStack() as stack:
        _entrar(stack, mocks, sem=("record",))
        stack.enter_context(
            patch(f"{_M}.record_job_run", AsyncMock(side_effect=RuntimeError("audit fora")))
        )
        crash = stack.enter_context(patch(f"{_M}.record_job_crash", AsyncMock()))
        rc = await account_resync.run()

    assert rc == 1
    crash.assert_not_awaited()


# --- 4. init_pool que falha deixa rastro estruturado ----------------------------------
@pytest.mark.asyncio
async def test_init_pool_que_falha_loga_erro_estruturado_e_re_levanta() -> None:
    """Sem pool não há audit possível: o rastro é uma linha ERROR com `event`,
    `operation` e `platform` (decisão de 11/11). A exceção sobe — o Cloud Run vê a
    execução falhar, que é o que a policy de job enxerga."""
    corpo = AsyncMock(return_value=0)
    with (
        patch.object(_runner.connection, "init_pool", AsyncMock(side_effect=OSError("dns"))),
        patch.object(_runner.connection, "close_pool", AsyncMock()) as close_pool,
        patch.object(_runner, "log", MagicMock()) as log,
        pytest.raises(OSError, match="dns"),
    ):
        await _runner.executar_job(
            operation="google_reconcile",
            platform="google",
            database_url="postgresql://x",
            corpo=corpo,
        )

    corpo.assert_not_awaited()
    close_pool.assert_not_awaited()
    log.error.assert_called_once()
    assert log.error.call_args.args == ("job_init_pool_failed",)
    kw = log.error.call_args.kwargs
    assert kw["operation"] == "google_reconcile"
    assert kw["platform"] == "google"
    assert "dns" in kw["error"]
