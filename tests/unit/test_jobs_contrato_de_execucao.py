"""Caracterização do contrato de execução dos jobs de reconciliação (Task H1).

Os dois jobs rodam em produção como Cloud Run Job, e o que o Cloud Run vê é
contrato: o exit code de cada combinação de falha, a ordem Google → Meta →
purge, que etapa ainda roda depois de outra falhar, o `record_job_crash` no
crash e o `close_pool` no `finally`. `test_account_resync.py` cobre boa parte
disso; aqui fica o que ele não afirmava e que uma refatoração do esqueleto
poderia mudar sem nenhum teste notar:

- crash no corpo Google e "sem OAuth" ENCERRAM o job — Meta e purge não rodam;
- a ordem das três etapas (nenhum teste afirmava Meta antes do purge);
- combinações de falha (Meta e purge falhando juntos, bloqueio Google com purge
  falhando) e o exit code de cada uma;
- `meta_resync.run()` fecha o pool nos três desfechos e não grava crash em
  bloqueio (bloqueio é exit 1 auditado por `reconcile_meta`, não crash).

Escrito PASSANDO no código anterior ao esqueleto comum — é caracterização, não
especificação nova.
"""

from __future__ import annotations

from contextlib import ExitStack
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.jobs import _audit, account_resync, meta_resync
from src.meta_ads.reconcile import Plan
from tests.unit.test_account_resync import _base_patches, _fake_pool, _reconcile_result

_M = "src.jobs.account_resync"
_CHAVES = (
    "init_pool",
    "close_pool",
    "get_pool",
    "pick",
    "derive",
    "decrypt",
    "build_client",
    "list_customers",
    "fetch",
    "reconcile_google",
    "avisar_sem_grant",
    "record",
    "purge",
)


def _entrar(
    stack: ExitStack, mocks: dict[str, Any], sem: tuple[str, ...] = (), *, log: bool = True
) -> None:
    for chave in _CHAVES:
        if chave not in sem:
            stack.enter_context(mocks[chave])
    if log:
        # `structlog.configure` é estado GLOBAL do processo pytest: rodá-lo de
        # verdade aqui quebra o `capture_logs()` de test_meta_denial_log.py,
        # coletado depois deste arquivo (mesma armadilha documentada em
        # test_job_partial_failure_audit.py).
        stack.enter_context(patch(f"{_M}.configure_logging", MagicMock()))


@pytest.mark.asyncio
async def test_ordem_das_etapas_e_google_meta_purge() -> None:
    ordem: list[str] = []
    mocks = _base_patches(pool=_fake_pool(MagicMock()), oc=SimpleNamespace(refresh_token_enc=b"e"))

    async def _google(*_a: Any, **_k: Any) -> dict[str, Any]:
        ordem.append("google")
        return _reconcile_result()

    async def _meta(*_a: Any, **_k: Any) -> Plan:
        ordem.append("meta")
        return Plan()

    async def _purge(*_a: Any, **_k: Any) -> dict[str, int]:
        ordem.append("purge")
        return {"pending_confirmations": 0}

    with ExitStack() as stack:
        _entrar(stack, mocks, sem=("reconcile_google", "purge"))
        stack.enter_context(patch(f"{_M}.reconcile_google", AsyncMock(side_effect=_google)))
        stack.enter_context(patch(f"{_M}.purge_expired", AsyncMock(side_effect=_purge)))
        stack.enter_context(
            patch("src.jobs.meta_resync.reconcile_meta", AsyncMock(side_effect=_meta))
        )
        rc = await account_resync.run()

    assert rc == 0
    assert ordem == ["google", "meta", "purge"]


@pytest.mark.asyncio
async def test_crash_no_corpo_google_nao_roda_meta_nem_purge() -> None:
    mocks = _base_patches(pool=_fake_pool(MagicMock()), oc=SimpleNamespace(refresh_token_enc=b"e"))
    meta = AsyncMock(return_value=Plan())
    with ExitStack() as stack:
        _entrar(stack, mocks, sem=("reconcile_google",))
        stack.enter_context(
            patch(f"{_M}.reconcile_google", AsyncMock(side_effect=RuntimeError("upsert caiu")))
        )
        stack.enter_context(patch("src.jobs.meta_resync.reconcile_meta", meta))
        crash = stack.enter_context(patch(f"{_M}.record_job_crash", AsyncMock()))
        with pytest.raises(RuntimeError, match="upsert caiu"):
            await account_resync.run()
        purge = mocks["purge"].new
        close_pool = mocks["close_pool"].new

    meta.assert_not_awaited()
    purge.assert_not_awaited()
    crash.assert_awaited_once()
    assert crash.await_args.kwargs["operation"] == "google_reconcile"
    close_pool.assert_awaited_once()


@pytest.mark.asyncio
async def test_sem_oauth_encerra_sem_meta_sem_purge_e_sem_crash() -> None:
    mocks = _base_patches(pool=_fake_pool(MagicMock()), oc=None)
    meta = AsyncMock(return_value=Plan())
    with ExitStack() as stack:
        _entrar(stack, mocks)
        stack.enter_context(patch("src.jobs.meta_resync.reconcile_meta", meta))
        crash = stack.enter_context(patch(f"{_M}.record_job_crash", AsyncMock()))
        rc = await account_resync.run()
        purge = mocks["purge"].new
        close_pool = mocks["close_pool"].new

    assert rc == 1
    meta.assert_not_awaited()
    purge.assert_not_awaited()
    crash.assert_not_awaited()
    close_pool.assert_awaited_once()


@pytest.mark.asyncio
async def test_meta_e_purge_falhando_juntos_sai_com_1_e_purge_e_tentado() -> None:
    mocks = _base_patches(pool=_fake_pool(MagicMock()), oc=SimpleNamespace(refresh_token_enc=b"e"))
    purge = AsyncMock(side_effect=RuntimeError("db down"))
    with ExitStack() as stack:
        _entrar(stack, mocks, sem=("purge",))
        stack.enter_context(patch(f"{_M}.purge_expired", purge))
        stack.enter_context(
            patch(
                "src.jobs.meta_resync.reconcile_meta",
                AsyncMock(side_effect=RuntimeError("meta down")),
            )
        )
        stack.enter_context(patch(f"{_M}.record_job_crash", AsyncMock()))
        rc = await account_resync.run()

    assert rc == 1
    purge.assert_awaited_once()


@pytest.mark.asyncio
async def test_bloqueio_google_com_purge_falhando_sai_com_1() -> None:
    mocks = _base_patches(
        pool=_fake_pool(MagicMock()),
        oc=SimpleNamespace(refresh_token_enc=b"e"),
        reconcile_result=_reconcile_result(blocked_reason="queda de 40%"),
    )
    meta = AsyncMock(return_value=Plan())
    with ExitStack() as stack:
        _entrar(stack, mocks, sem=("purge",))
        stack.enter_context(patch(f"{_M}.purge_expired", AsyncMock(side_effect=RuntimeError("x"))))
        stack.enter_context(patch("src.jobs.meta_resync.reconcile_meta", meta))
        rc = await account_resync.run()

    assert rc == 1
    meta.assert_awaited_once()


@pytest.mark.asyncio
async def test_so_o_purge_falhando_nao_muda_o_exit_code_nem_grava_crash() -> None:
    mocks = _base_patches(pool=_fake_pool(MagicMock()), oc=SimpleNamespace(refresh_token_enc=b"e"))
    with ExitStack() as stack:
        _entrar(stack, mocks, sem=("purge",))
        stack.enter_context(patch(f"{_M}.purge_expired", AsyncMock(side_effect=RuntimeError("x"))))
        stack.enter_context(
            patch("src.jobs.meta_resync.reconcile_meta", AsyncMock(return_value=Plan()))
        )
        crash = stack.enter_context(patch(f"{_M}.record_job_crash", AsyncMock()))
        rc = await account_resync.run()

    assert rc == 0
    crash.assert_not_awaited()


@pytest.mark.asyncio
async def test_logging_configurado_antes_do_pool_no_job_google() -> None:
    ordem: list[str] = []
    mocks = _base_patches(pool=_fake_pool(MagicMock()), oc=None)
    with ExitStack() as stack:
        _entrar(stack, mocks, sem=("init_pool",), log=False)
        stack.enter_context(
            patch(f"{_M}.configure_logging", MagicMock(side_effect=lambda **_: ordem.append("log")))
        )
        stack.enter_context(
            patch(
                f"{_M}.connection.init_pool",
                AsyncMock(side_effect=lambda *_a, **_k: ordem.append("pool")),
            )
        )
        await account_resync.run()

    assert ordem == ["log", "pool"]


class _FakeAcquire:
    async def __aenter__(self) -> MagicMock:
        return MagicMock()

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakePool:
    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire()


def _preparar_meta(monkeypatch: pytest.MonkeyPatch, reconcile: AsyncMock) -> dict[str, Any]:
    ordem: list[str] = []
    settings = MagicMock()
    settings.database_url = "postgres://fake"
    monkeypatch.setattr(meta_resync, "get_settings", lambda: settings)
    monkeypatch.setattr(
        meta_resync, "configure_logging", MagicMock(side_effect=lambda **_: ordem.append("log"))
    )
    init_pool = AsyncMock(side_effect=lambda *_a, **_k: ordem.append("pool"))
    close_pool = AsyncMock()
    monkeypatch.setattr(meta_resync.connection, "init_pool", init_pool)
    monkeypatch.setattr(meta_resync.connection, "close_pool", close_pool)
    monkeypatch.setattr(meta_resync.connection, "get_pool", lambda: _FakePool())
    monkeypatch.setattr(meta_resync, "reconcile_meta", reconcile)
    rec = AsyncMock(return_value=1)
    monkeypatch.setattr(_audit, "record_job_run", rec)
    return {"ordem": ordem, "init_pool": init_pool, "close_pool": close_pool, "crash_rec": rec}


@pytest.mark.asyncio
async def test_meta_run_sucesso_fecha_pool_e_configura_log_antes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m = _preparar_meta(monkeypatch, AsyncMock(return_value=Plan()))
    assert await meta_resync.run() == 0
    assert m["ordem"] == ["log", "pool"]
    m["init_pool"].assert_awaited_once_with("postgres://fake")
    m["close_pool"].assert_awaited_once()
    m["crash_rec"].assert_not_awaited()


@pytest.mark.asyncio
async def test_meta_run_bloqueio_sai_com_1_sem_crash_e_fecha_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m = _preparar_meta(monkeypatch, AsyncMock(return_value=Plan(blocked_reason="truncada")))
    assert await meta_resync.run() == 1
    m["close_pool"].assert_awaited_once()
    m["crash_rec"].assert_not_awaited()


@pytest.mark.asyncio
async def test_meta_run_crash_audita_repropaga_e_fecha_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m = _preparar_meta(monkeypatch, AsyncMock(side_effect=RuntimeError("graph caiu")))
    with pytest.raises(RuntimeError, match="graph caiu"):
        await meta_resync.run()
    kwargs = m["crash_rec"].await_args.kwargs
    assert kwargs["operation"] == "meta_reconcile"
    assert kwargs["platform"] == "meta"
    assert kwargs["status"] == "error"
    m["close_pool"].assert_awaited_once()
