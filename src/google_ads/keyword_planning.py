"""Executor generico de leitura fora do GAQL (planejador de palavras-chave).

KeywordPlanIdeaService e GeoTargetConstantService nao passam por
`GoogleAdsService.search_stream`, entao `run_report` nao serve. Este executor
da a essas chamadas a mesma governanca dos demais: hard-gate de acesso (nivel
`read`), reserva de quota (token global + `mgr:<uuid>`, F73), chamada SDK fora
do event loop (F86/F109), bookkeeping best-effort (F83) e audit sempre.

Nao ha logica do planejador aqui: `chamadas` e codigo da tool, recebe o
`GoogleAdsClient` e roda DENTRO do `run_blocking`.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sized
from typing import Any
from uuid import UUID

import structlog

from src.blocking import run_blocking
from src.config import get_settings
from src.db import connection
from src.db.repositories import audit_log
from src.google_ads.access import ensure_account_access
from src.google_ads.client import build_client_for_manager
from src.google_ads.errors import to_friendly
from src.google_ads.request_id import get_request_id, reset_request_id
from src.governance.bookkeeping import best_effort
from src.governance.rate_limit import (
    QuotaExhausted,
    before_call,
    hash_developer_token,
    record_actual,
)

log = structlog.get_logger(__name__)


async def run_keyword_planning[T](
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    operation_name: str,
    estimated_ops: int,
    params_summary: dict[str, Any],
    chamadas: Callable[[Any], T],
    resumo_do_resultado: Callable[[T], dict[str, Any]] | None = None,
) -> T:
    """Roda `chamadas(client)` numa thread, sob gate de leitura + quota + audit.

    Erros do SDK sobem como `GoogleAdsFriendlyError` depois do bookkeeping.
    `resumo_do_resultado`, se dado, roda so em sucesso e seu dict e MESCLADO em
    `params_summary` do audit (o que so se sabe depois da chamada, ex.: falhas parciais).
    """
    settings = get_settings()
    # F91 — gate a cada request MCP; negacao levanta antes de qualquer reserva.
    await connection.run_with_reconnect(
        lambda conn: ensure_account_access(
            conn,
            manager_id=manager_id,
            customer_id=customer_id,
            session_id=session_id,
            operation_name=operation_name,
            level="read",
        )
    )

    token_id = hash_developer_token(settings.google_ads_developer_token)
    started = time.monotonic()
    pool = connection.get_pool()
    status = "success"
    error_message: str | None = None
    friendly_error: Exception | None = None
    original_error: Exception | None = None
    reserved = False
    resultado: T | None = None
    # Lido DENTRO do closure: o ContextVar do interceptor nao volta da thread.
    request_id: list[str | None] = []
    target_count: int | None = None

    try:
        # Transacao EXTERNA: as duas reservas sao tudo-ou-nada (F73).
        async with pool.acquire() as conn, conn.transaction():
            dia = await before_call(conn, token_id, estimated_ops=estimated_ops)
            dia_do_gestor = await before_call(
                conn,
                f"mgr:{manager_id}",
                estimated_ops=estimated_ops,
                daily_limit=settings.manager_daily_quota,
            )
        reserved = True

        client = await build_client_for_manager(manager_id=manager_id)

        def _executar() -> T:
            reset_request_id()
            try:
                return chamadas(client)
            finally:
                request_id.append(get_request_id())

        resultado = await run_blocking(_executar)
        if isinstance(resultado, Sized):
            target_count = len(resultado)
        if resumo_do_resultado is not None:
            try:
                params_summary = {**params_summary, **resumo_do_resultado(resultado)}
            except Exception:
                # O resumo e enfeite do audit: nao pode transformar leitura boa em erro.
                log.exception(
                    "run_keyword_planning_resumo_failed",
                    customer_id=customer_id,
                    operation=operation_name,
                )
    except QuotaExhausted as e:
        # Negacao por quota e esperada e a mensagem PT-BR ja e curada (qual
        # cota, usado/limite, reset): sobe INTACTA, sem to_friendly (que a
        # trocaria por "Erro inesperado"), igual a run_report.
        status = "error"
        error_message = str(e)
        log.warning(
            "run_keyword_planning_quota_exhausted",
            customer_id=customer_id,
            operation=operation_name,
        )
        friendly_error = e
        original_error = None
    except Exception as e:
        status = "error"
        error_message = str(e)
        log.exception(
            "run_keyword_planning_failed",
            customer_id=customer_id,
            operation=operation_name,
        )
        friendly_error = to_friendly(e)
        original_error = e
    finally:
        duration_ms = int((time.monotonic() - started) * 1000)
        actual_ops = estimated_ops if status == "success" else 0
        # F73: so reconcilia o que foi reservado.
        if reserved:
            async with (
                best_effort(
                    "keyword_planning_quota_reconcile_failed",
                    operation=operation_name,
                    customer_id=customer_id,
                ),
                pool.acquire() as conn,
                conn.transaction(),
            ):
                await record_actual(
                    conn, token_id, dia=dia, actual_ops=actual_ops, estimated_ops=estimated_ops
                )
                await record_actual(
                    conn,
                    f"mgr:{manager_id}",
                    dia=dia_do_gestor,
                    actual_ops=actual_ops,
                    estimated_ops=estimated_ops,
                )
        # Audit SEMPRE (inclusive negacao por quota); falha vira ERROR (F83).
        async with (
            best_effort(
                "keyword_planning_audit_write_failed",
                operation=operation_name,
                customer_id=customer_id,
                status=status,
            ),
            pool.acquire() as conn,
        ):
            await audit_log.record(
                conn,
                manager_id=manager_id,
                session_id=session_id,
                customer_id=customer_id,
                action_type="read",
                platform="google",
                operation=operation_name,
                target_count=target_count,
                params_summary=params_summary,
                # Nao capturado e `None` (nao medido), nunca "".
                provider_request_id=request_id[-1] if request_id else None,
                status=status,
                error_message=error_message,
                duration_ms=duration_ms,
            )

    if friendly_error is not None:
        if original_error is None:
            raise friendly_error
        raise friendly_error from original_error
    return resultado  # type: ignore[return-value]
