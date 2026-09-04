# bucket: defer
"""Tool: get_my_audit_log — paginated history das operações do gestor logado."""

import time
from typing import Any

import structlog

from src.db import connection
from src.db.repositories import audit_log
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

log = structlog.get_logger(__name__)

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "days": {
            "type": "integer",
            "minimum": 1,
            "maximum": 30,
            "default": 7,
            "description": "Janela de tempo em dias (1-30, default 7).",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 1000,
            "default": 100,
            "description": "Numero maximo de eventos retornados (1-1000, default 100).",
        },
        "customer_id": {
            "type": "string",
            "pattern": "^[0-9]{10}$",
            "description": "Filtrar por uma conta especifica (opcional).",
        },
        "action_type": {
            "type": "string",
            "enum": ["mutate", "read", "auth", "system", "all"],
            "default": "all",
            "description": "Filtrar por tipo de acao. 'all' = sem filtro.",
        },
    },
    "additionalProperties": False,
}


@register_tool(
    name="get_my_audit_log",
    description=(
        "[DEFER] Historico das proprias operacoes do gestor via MCP (mutations + audited "
        "reads), com filtros por janela de tempo, conta, e tipo de acao. Retorna "
        "ordenado por occurred_at DESC. Scoped automaticamente ao gestor logado. "
        "**`dry_run` separa TENTATIVA de APLICACAO** (F148): `true` = preview que mintou "
        "token e pode nunca ter sido aplicado; `false`/ausente = mutacao real ou linha "
        "anterior ao fix. Sem esse campo os dois casos sao identicos, porque ambos gravam "
        "`action_type: mutate` com o `target_count` planejado — nao tente distinguir por "
        "`duration_ms`. Um mesmo preview tambem deixa uma linha `read` ao lado, que e a "
        "consulta GAQL que ele fez, nao o preview."
    ),
    input_schema=_INPUT_SCHEMA,
    bucket="defer",
)
async def get_my_audit_log(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    started = time.monotonic()

    days = args.get("days", 7)
    limit = args.get("limit", 100)
    customer_id = args.get("customer_id")
    action_type = args.get("action_type", "all")

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        events = await audit_log.list_for_manager(
            conn,
            manager_id=ctx.manager_id,
            days=days,
            limit=limit,
            customer_id=customer_id,
            action_type=action_type,
        )

    duration_ms = int((time.monotonic() - started) * 1000)

    # Audit consistent com list_my_accounts (account-wide read).
    async with pool.acquire() as conn:
        await audit_log.record(
            conn,
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            action_type="read",
            operation="get_my_audit_log",
            target_count=len(events),
            params_summary={
                "days": days,
                "limit": limit,
                "action_type": action_type,
            },
            status="success",
            duration_ms=duration_ms,
        )

    log.info(
        "tool_get_my_audit_log",
        manager_id=str(ctx.manager_id),
        count=len(events),
        days=days,
        duration_ms=duration_ms,
    )

    return {
        "manager_id": str(ctx.manager_id),
        "filters": {
            "days": days,
            "customer_id": customer_id,
            "action_type": action_type,
        },
        "count": len(events),
        "events": events,
    }
