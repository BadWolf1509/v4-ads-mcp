"""Helper de reserva/reconcile de cota dos executores Google (DB real)."""

from uuid import uuid4

import pytest

from src.config import get_settings
from src.governance.rate_limit import CHAVE_COTA_PROJETO, QuotaExhausted, before_call
from src.governance.reserva import Reserva, reconciliar_cota, reservar_cota


async def _usado(pool, chave: str, dia) -> int | None:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT operations_used FROM rate_counters WHERE developer_token_id = $1 AND date = $2",
            chave,
            dia,
        )


@pytest.mark.integration
async def test_reserva_e_reconcile_movem_as_duas_chaves(db) -> None:
    manager_id = uuid4()
    reserva = await reservar_cota(db, manager_id=manager_id, estimated_ops=5)
    assert isinstance(reserva, Reserva)
    assert reserva.estimated_ops == 5
    assert await _usado(db, CHAVE_COTA_PROJETO, reserva.dia_projeto) == 5
    assert await _usado(db, f"mgr:{manager_id}", reserva.dia_gestor) == 5

    await reconciliar_cota(db, reserva, manager_id=manager_id, actual_ops=2, evento="x_falhou")

    assert await _usado(db, CHAVE_COTA_PROJETO, reserva.dia_projeto) == 2
    assert await _usado(db, f"mgr:{manager_id}", reserva.dia_gestor) == 2


@pytest.mark.integration
async def test_limite_do_gestor_desfaz_reserva_do_projeto(db) -> None:
    manager_id = uuid4()
    limite = get_settings().manager_daily_quota
    async with db.acquire() as conn:
        dia = await before_call(conn, f"mgr:{manager_id}", estimated_ops=limite)

    with pytest.raises(QuotaExhausted):
        await reservar_cota(db, manager_id=manager_id, estimated_ops=1)

    assert await _usado(db, CHAVE_COTA_PROJETO, dia) in (None, 0)
    assert await _usado(db, f"mgr:{manager_id}", dia) == limite


class _PoolQueQuebra:
    def acquire(self):
        raise ConnectionError("conexao stale")


@pytest.mark.integration
async def test_reconcile_engole_falha(db) -> None:
    manager_id = uuid4()
    reserva = await reservar_cota(db, manager_id=manager_id, estimated_ops=3)
    # Nao levanta: o bookkeeping nao decide o resultado da operacao (F83).
    await reconciliar_cota(
        _PoolQueQuebra(), reserva, manager_id=manager_id, actual_ops=1, evento="x_falhou"
    )
    # A reserva ficou como estava (nada foi acertado).
    assert await _usado(db, CHAVE_COTA_PROJETO, reserva.dia_projeto) == 3
