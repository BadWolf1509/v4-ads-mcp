# bucket: always
"""List Meta Ad Accounts the manager has access to (Sprint M.2a Task 9).

Source: manager_meta_account_access (os acessos que o admin concede) cruzado com
meta_ad_accounts (o inventário, que só o resync diário escreve — F197).
Does NOT call Meta API.
"""

import time
from typing import Any

from src.db import connection
from src.db.repositories import audit_log, manager_meta_account_access
from src.governance.bookkeeping import best_effort
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool
from src.meta_ads.labels import META_ACCOUNT_STATUS_LABELS

_DESCRIPTION = (
    "[CORE] Lista as contas de anúncio Meta às quais o gestor tem acesso. "
    "Fonte: o inventário local (a parceria do BM da V4, sincronizada pelo resync "
    "diário das 06:00, horário de Brasília) cruzado com os acessos que o admin "
    "concedeu ao gestor. Conta nova entra na execução seguinte do resync; se faltar "
    "alguma, peça ao admin. "
    "Retorna: ad_account_id ('act_<numeric>'), account_name, business_id/name "
    "(NULL se personal), currency, timezone_name, account_status (Meta enum) "
    "+ account_status_label (PT-BR)."
)


@register_tool(
    name="meta_list_my_ad_accounts",
    description=_DESCRIPTION,
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    bucket="always",
)
async def handler(_args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    started = time.monotonic()
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        accounts = await manager_meta_account_access.list_accounts_for_manager(conn, ctx.manager_id)

    # A-01: a leitura grava uma linha, como a irmã Google (`list_my_accounts`).
    # Conexão nova e `best_effort`: audit que falha não derruba a lista (F83).
    async with (
        best_effort("meta_list_audit_write_failed", operation="meta_list_my_ad_accounts"),
        pool.acquire() as conn,
    ):
        await audit_log.record(
            conn,
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=None,
            action_type="read",
            operation="meta_list_my_ad_accounts",
            target_count=len(accounts),
            params_summary=None,
            status="success",
            duration_ms=int((time.monotonic() - started) * 1000),
            platform="meta",
        )

    return {
        "ad_accounts": [
            {
                "ad_account_id": a.ad_account_id,
                "account_name": a.account_name,
                "business_id": a.business_id,
                "business_name": a.business_name,
                "currency": a.currency,
                "timezone_name": a.timezone_name,
                "account_status": a.account_status,
                "account_status_label": META_ACCOUNT_STATUS_LABELS.get(
                    a.account_status or 0, "DESCONHECIDO"
                ),
            }
            for a in accounts
        ],
        "total": len(accounts),
    }
