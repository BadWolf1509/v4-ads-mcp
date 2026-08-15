"""Audit row compartilhado pra jobs de background (resync, etc.).

Jobs rodam sem contexto de manager/session → manager_id/session_id None
(audit_log.manager_id é nullable, 001_initial_schema.sql:73). action_type
'system' é permitido pelo audit_action_type_check.
"""

from typing import Any, Literal

import asyncpg
import structlog

from src.db import connection
from src.db.repositories import audit_log
from src.governance.bookkeeping import best_effort

log = structlog.get_logger(__name__)


async def record_job_crash(
    *,
    operation: str,
    platform: Literal["google", "meta"],
    exc: BaseException,
) -> None:
    """Grava `status=error` pra crash INESPERADO de job (F93), sem mascarar o crash.

    Sem isto, uma excecao no corpo do job (build_client, fetch, upsert_many,
    rede) nao deixa NENHUMA linha no audit — o rastro fica so no Cloud Run, e um
    job quebrado por dias fica invisivel na trilha de auditoria.

    O `best_effort` e o mesmo do F83, e pela mesma razao: o audit do crash nao
    pode virar um segundo crash que substitui o original.
    """
    async with (
        best_effort("job_crash_audit_failed", operation=operation),
        connection.get_pool().acquire() as conn,
    ):
        await record_job_run(
            conn,
            operation=operation,
            platform=platform,
            status="error",
            error_message=str(exc)[:500],
        )


async def record_job_run(
    conn: asyncpg.Connection,
    *,
    operation: str,
    status: str,
    platform: Literal["google", "meta"] = "google",
    target_count: int | None = None,
    error_message: str | None = None,
    params_summary: dict[str, Any] | None = None,
) -> int:
    """Grava 1 linha audit_log marcando um run de job. Retorna o id da linha.

    `status` e OBRIGATORIO de proposito (F93): quando tinha default "success", o
    `resync_meta` reportava sucesso sobre inventario truncado simplesmente por
    nao passar o argumento. Sem default, cada call-site e forcado a decidir.
    Valores aceitos pelo constraint do banco: success | error | denied.
    """
    return await audit_log.record(
        conn,
        manager_id=None,
        session_id=None,
        customer_id=None,
        action_type="system",
        operation=operation,
        target_count=target_count,
        params_summary=params_summary,
        status=status,
        error_message=error_message,
        platform=platform,
    )
