"""Encerramento comum dos executores Google: reconcile de cota e audit (P6).

Os 6 executores Google (`run_report`, `run_keyword_planning`,
`run_offline_user_data_job`, `run_conversion_upload`, `run_mutation`,
`run_recommendation_action`) terminavam no mesmo `finally`, escrito a mao em
cada um — e foi ali que moraram F73 (reconciliar sem ter reservado), F83
(excecao no `finally` descarta o `return` de uma mutacao ja aplicada) e F91.
`encerrar_execucao` e esse `finally`, uma vez so.

O que NAO veio para ca, de proposito: o gate (`ensure_account_access`, no topo
de cada executor, fora de `try`), a reserva e o `try/except` de cada um — a
traducao de erro difere de verdade entre eles.

Dois statements irmaos, independentes (F83): a falha do reconcile nao pula o
audit, e nenhum dos dois levanta. O montador do audit e chamado DENTRO do
`best_effort` e depois do `acquire`: e la que o upload de conversoes calcula o
status da trilha e o resumo, e uma excecao nesse calculo, fora do
`best_effort`, descartaria o `return` de um upload ja feito.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, Literal
from uuid import UUID

from src.db.connection import PoolValidado
from src.db.repositories import audit_log
from src.governance.bookkeeping import best_effort
from src.governance.reserva import Reserva, reconciliar_cota


@dataclass(frozen=True, slots=True)
class RegistroDeAudit:
    """Os kwargs de `audit_log.record` que os executores Google passam."""

    manager_id: UUID
    session_id: UUID
    customer_id: str
    action_type: Literal["read", "mutate"]
    operation: str
    status: str
    target_count: int | None = None
    params_summary: dict[str, Any] | None = None
    provider_request_id: str | None = None
    error_message: str | None = None
    duration_ms: int | None = None
    platform: Literal["google", "meta"] = "google"
    had_effect: bool | None = None


async def encerrar_execucao(
    pool: PoolValidado,
    reserva: Reserva | None,
    *,
    manager_id: UUID,
    actual_ops: int,
    operation: str,
    customer_id: str,
    status: str,
    evento_cota: str,
    evento_audit: str,
    montar_audit: Callable[[], RegistroDeAudit] | None,
) -> None:
    """Reconcilia a cota (se reservou) e grava o audit (se ha montador), sem levantar.

    `reserva is None` = a reserva nao foi persistida (ex.: `QuotaExhausted`), e
    reconciliar mesmo assim decrementaria o contador sem contrapartida (F73).
    `montar_audit is None` = esta chamada nao audita (`run_report` sem opt-in):
    nenhuma conexao e pedida. `evento_cota`/`evento_audit` nomeiam o log ERROR do
    `best_effort` de cada bloco.
    """
    if reserva is not None:
        await reconciliar_cota(
            pool,
            reserva,
            manager_id=manager_id,
            actual_ops=actual_ops,
            evento=evento_cota,
            operation=operation,
            customer_id=customer_id,
        )
    if montar_audit is not None:
        async with (
            best_effort(evento_audit, operation=operation, customer_id=customer_id, status=status),
            pool.acquire() as conn,
        ):
            await audit_log.record(conn, **asdict(montar_audit()))
