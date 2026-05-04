"""Tool: list_my_accounts — returns Google Ads accounts the caller can operate."""

import time
from typing import Any

import structlog

from src.db import connection
from src.db.repositories import audit_log, manager_account_access
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

log = structlog.get_logger(__name__)


_INPUT_SCHEMA = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


@register_tool(
    name="list_my_accounts",
    description=(
        "Lista as contas Google Ads que o gestor logado tem permissão pra operar. "
        "Retorna o customer_id (sem traços), nome, moeda, fuso e flag de conta de teste. "
        "Sem parâmetros — usa a sessão MCP pra identificar o gestor."
    ),
    input_schema=_INPUT_SCHEMA,
)
async def list_my_accounts(_args: dict[str, Any]) -> list[dict[str, Any]]:
    ctx = get_current()
    started = time.monotonic()

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        accounts = await manager_account_access.list_accounts_for_manager(conn, ctx.manager_id)

    result = [
        {
            "customer_id": a.customer_id,
            "descriptive_name": a.descriptive_name,
            "mcc_id": a.mcc_id,
            "currency_code": a.currency_code,
            "time_zone": a.time_zone,
            "is_test_account": a.is_test_account,
        }
        for a in accounts
    ]

    duration_ms = int((time.monotonic() - started) * 1000)

    # Audit (read action_type so it's discoverable, but it's a small list).
    async with pool.acquire() as conn:
        await audit_log.record(
            conn,
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=None,
            action_type="read",
            operation="list_my_accounts",
            target_count=len(result),
            params_summary=None,
            status="success",
            duration_ms=duration_ms,
        )

    log.info("tool_list_my_accounts", count=len(result), duration_ms=duration_ms)
    return result
