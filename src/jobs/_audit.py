"""Audit row compartilhado pra jobs de background (resync, etc.).

Jobs rodam sem contexto de manager/session → manager_id/session_id None
(audit_log.manager_id é nullable, 001_initial_schema.sql:73). action_type
'system' é permitido pelo audit_action_type_check.
"""

from typing import Any, Literal

import asyncpg

from src.db.repositories import audit_log


async def record_job_run(
    conn: asyncpg.Connection,
    *,
    operation: str,
    platform: Literal["google", "meta"] = "google",
    target_count: int | None = None,
    status: str = "success",
    error_message: str | None = None,
    params_summary: dict[str, Any] | None = None,
) -> int:
    """Grava 1 linha audit_log marcando um run de job. Retorna o id da linha."""
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
