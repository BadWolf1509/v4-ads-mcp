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


async def record_access_revocation(
    conn: asyncpg.Connection,
    *,
    platform: Literal["google", "meta"],
    ad_account_id: str,
    reason: str,
    manager_ids: list[str],
) -> int:
    """Grava a revogação automática de acesso de UMA conta (Google ou Meta).

    Por conta e não por grant: a lista de gestores cabe no `params_summary` e
    uma linha por grant inundaria a trilha sem acrescentar forense.

    `ad_account_id` é o identificador da conta na respectiva plataforma —
    `customer_id` no Google, `ad_account_id` no Meta (o nome do parâmetro
    ficou do gêmeo Meta, que existia primeiro); nos dois casos vira
    `customer_id` na mesma coluna do audit_log. `platform` é obrigatório de
    propósito (mesma razão do F93 pra `status` em `record_job_run`): sem
    default, quem chama é forçado a decidir, e `operation` sai dele
    (`f"{platform}_access_cleanup"`) — generalizado na revisão de branch
    Google (C2, 2026-09-05); o comportamento pro Meta é bit-a-bit o mesmo de
    antes, só com `platform="meta"` explícito no call site.

    `action_type="mutate"` porque é o que é. Sob token de system user (Meta) ou
    OAuth de admin (Google) a auditoria do próprio provedor não distingue
    gestor, então esta linha é o único lugar onde fica registrado que um
    acesso humano foi retirado, e por quê — nos dois lados.
    """
    return await audit_log.record(
        conn,
        manager_id=None,
        session_id=None,
        customer_id=ad_account_id,
        action_type="mutate",
        operation=f"{platform}_access_cleanup",
        target_count=len(manager_ids),
        params_summary={"reason": reason, "managers": manager_ids},
        status="success",
        error_message=None,
        platform=platform,
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
