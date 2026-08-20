# bucket: defer
"""Tool: get_my_rate_limit_status — quota diaria do gestor E da conta V4.

Desde o F73 cada chamada reserva contra DUAS chaves: o developer token da V4
(compartilhado por todos) e `mgr:<uuid>` (cap por gestor). Como o cap por
gestor e menor, e quase sempre ELE que barra primeiro — e este tool so lia o
global, entao respondia "34% usado, pode seguir" pra quem ja estava travado.
"""

import time
from datetime import UTC, datetime
from typing import Any

import structlog

from src.config import get_settings
from src.db import connection
from src.db.repositories import audit_log
from src.governance.rate_limit import (
    DAILY_QUOTA_BASIC,
    WARN_THRESHOLD_PCT,
    Usage,
    get_today_usage,
    hash_developer_token,
)
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

log = structlog.get_logger(__name__)

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


@register_tool(
    name="get_my_rate_limit_status",
    description=(
        "[DEFER] Quota diaria do dia UTC atual em DOIS niveis: `manager` (seu cap "
        "pessoal) e `account` (developer token da V4, compartilhado por todos os "
        "gestores e todas as contas). `blocking_scope` diz qual dos dois esgota "
        "primeiro — normalmente o seu, que e menor. Sem parametros. Reset a "
        "meia-noite UTC."
    ),
    input_schema=_INPUT_SCHEMA,
    bucket="defer",
)
async def get_my_rate_limit_status(_args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    started = time.monotonic()
    settings = get_settings()
    token_hash = hash_developer_token(settings.google_ads_developer_token)

    # NOTE: DAILY_QUOTA_BASIC hardcoded. After Standard Access (case 26521440673)
    # approves, update DAILY_QUOTA_BASIC constant in rate_limit.py to
    # DAILY_QUOTA_STANDARD value (1_000_000). 1-line change, out of scope here.
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        conta = await get_today_usage(conn, token_hash, daily_limit=DAILY_QUOTA_BASIC)
        # Mesma tabela, chave `mgr:<uuid>` — e o que before_call reserva em cada
        # executor desde o F73. Ler daqui e uma linha; nao ler era o bug.
        gestor = await get_today_usage(
            conn,
            f"mgr:{ctx.manager_id}",
            daily_limit=settings.manager_daily_quota,
        )

    duration_ms = int((time.monotonic() - started) * 1000)

    # Audit consistent com list_my_accounts (account-wide read).
    async with pool.acquire() as conn:
        await audit_log.record(
            conn,
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=None,
            action_type="read",
            operation="get_my_rate_limit_status",
            target_count=1,
            params_summary=None,
            status="success",
            duration_ms=duration_ms,
        )

    log.info(
        "tool_get_my_rate_limit_status",
        conta_used=conta.used,
        conta_limit=conta.limit,
        gestor_used=gestor.used,
        gestor_limit=gestor.limit,
        duration_ms=duration_ms,
    )

    def _bloco(u: Usage) -> dict[str, Any]:
        return {
            "used": u.used,
            "limit": u.limit,
            "remaining": max(0, u.limit - u.used),
            "pct": round(u.pct, 4),
            "pct_display": f"{u.pct * 100:.1f}%",
        }

    # Quem esgota primeiro em numero ABSOLUTO de chamadas restantes — e isso que
    # o gestor sente. Percentual enganaria: 90% de 15.000 sobra mais que 50% de
    # 5.000. Os dois blocos vao inteiros pra quem quiser conferir a conta.
    escopo = "manager" if (gestor.limit - gestor.used) <= (conta.limit - conta.used) else "account"

    return {
        "date_utc": datetime.now(UTC).date().isoformat(),
        "blocking_scope": escopo,
        "manager": _bloco(gestor),
        "account": {**_bloco(conta), "developer_token_id_hash": token_hash},
        "warning_threshold_pct": WARN_THRESHOLD_PCT,
    }
