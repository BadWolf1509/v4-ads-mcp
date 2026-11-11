"""Reserva e reconcile da cota diaria dos executores Google.

Todo executor Google reserva duas chaves de cota antes de chamar a API (a do projeto
dono do cliente OAuth e o teto por gestor) e, no `finally`, acerta as duas com o
consumo real. Este modulo concentra esse par para os executores nao divergirem.

Reserva: transacao EXTERNA torna as duas tudo-ou-nada (o `conn.transaction()` interno
de `before_call` vira SAVEPOINT; `QuotaExhausted` em qualquer uma desfaz ambas) — F73.
Reconcile: best-effort (F83); so deve ser chamado se a reserva foi persistida, senao
decrementaria o contador sem contrapartida.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from src.config import get_settings
from src.db.connection import PoolValidado
from src.governance.bookkeeping import best_effort
from src.governance.rate_limit import CHAVE_COTA_PROJETO, before_call, record_actual


@dataclass(frozen=True)
class Reserva:
    """O que `reservar_cota` persistiu: os dias (UTC) de cada balde e a estimativa."""

    dia_projeto: date
    dia_gestor: date
    estimated_ops: int


async def reservar_cota(pool: PoolValidado, *, manager_id: UUID, estimated_ops: int) -> Reserva:
    """Reserva `estimated_ops` na chave do projeto e na do gestor, tudo-ou-nada.

    `QuotaExhausted` sobe intacto (nada fica reservado).
    """
    settings = get_settings()
    async with pool.acquire() as conn, conn.transaction():
        dia_projeto = await before_call(conn, CHAVE_COTA_PROJETO, estimated_ops=estimated_ops)
        dia_gestor = await before_call(
            conn,
            f"mgr:{manager_id}",
            estimated_ops=estimated_ops,
            daily_limit=settings.manager_daily_quota,
        )
    return Reserva(dia_projeto=dia_projeto, dia_gestor=dia_gestor, estimated_ops=estimated_ops)


async def reconciliar_cota(
    pool: PoolValidado,
    reserva: Reserva,
    *,
    manager_id: UUID,
    actual_ops: int,
    evento: str,
    **contexto: Any,
) -> None:
    """Acerta as duas chaves com o consumo real, engolindo falha (F83).

    `evento` e `contexto` alimentam o log ERROR do `best_effort` se algo falhar.
    """
    async with (
        best_effort(evento, **contexto),
        pool.acquire() as conn,
        conn.transaction(),
    ):
        await record_actual(
            conn,
            CHAVE_COTA_PROJETO,
            dia=reserva.dia_projeto,
            actual_ops=actual_ops,
            estimated_ops=reserva.estimated_ops,
        )
        await record_actual(
            conn,
            f"mgr:{manager_id}",
            dia=reserva.dia_gestor,
            actual_ops=actual_ops,
            estimated_ops=reserva.estimated_ops,
        )
