"""F83: `reconciliar_cota` nunca propaga falha de I/O de cota.

Os executores Google chamam essa funcao dentro do `finally`; excecao ali descarta o
`return` de uma operacao ja aplicada. Teste comportamental da funcao isolada, para
nao depender de um executor inteiro nem do banco (o `test_reconcile_engole_falha`
de integracao so roda com Docker).
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.governance import bookkeeping
from src.governance.reserva import Reserva, reconciliar_cota


class _ConexaoStaleError(Exception):
    """Stand-in pro asyncpg.ConnectionDoesNotExistError do F76."""


def _pool_ok() -> MagicMock:
    conn = AsyncMock()
    txn = MagicMock()
    txn.__aenter__ = AsyncMock(return_value=None)
    txn.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=txn)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.acquire.return_value = cm
    return pool


def _pool_stale_no_acquire() -> MagicMock:
    pool = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(side_effect=_ConexaoStaleError("stale"))
    cm.__aexit__ = AsyncMock(return_value=None)
    pool.acquire.return_value = cm
    return pool


_RESERVA = Reserva(dia_projeto=date(2026, 11, 3), dia_gestor=date(2026, 11, 3), estimated_ops=5)


async def _reconciliar(pool: MagicMock) -> None:
    await reconciliar_cota(
        pool,
        _RESERVA,
        manager_id=uuid4(),
        actual_ops=3,
        evento="teste_quota_reconcile_failed",
        operation="op",
    )


@pytest.mark.asyncio
async def test_falha_no_acquire_nao_propaga_e_deixa_log_error() -> None:
    with patch.object(bookkeeping.log, "exception") as log_mock:
        await _reconciliar(_pool_stale_no_acquire())
    log_mock.assert_called_once()
    assert log_mock.call_args.args[0] == "teste_quota_reconcile_failed"


@pytest.mark.asyncio
async def test_falha_no_record_actual_nao_propaga_e_deixa_log_error() -> None:
    with (
        patch(
            "src.governance.reserva.record_actual",
            AsyncMock(side_effect=_ConexaoStaleError("stale")),
        ),
        patch.object(bookkeeping.log, "exception") as log_mock,
    ):
        await _reconciliar(_pool_ok())
    log_mock.assert_called_once()


@pytest.mark.asyncio
async def test_caminho_feliz_acerta_as_duas_chaves() -> None:
    record = AsyncMock()
    with patch("src.governance.reserva.record_actual", record):
        await _reconciliar(_pool_ok())
    assert record.await_count == 2
