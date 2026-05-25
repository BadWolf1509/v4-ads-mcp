# bucket: always
"""List Meta Ad Accounts the manager has access to (Sprint M.2a Task 9).

Source: manager_meta_account_access (local cache, populated on OAuth callback).
Does NOT call Meta API. Reconnect via webapp to refresh.
"""

from typing import Any

from src.db import connection
from src.db.repositories import manager_meta_account_access
from src.mcp.context import get_current
from src.mcp.tools._meta_common import META_ACCOUNT_STATUS_LABELS
from src.mcp.tools._registry import register_tool

_DESCRIPTION = (
    "Lista as contas de anúncio Meta às quais o gestor tem acesso. "
    "Fonte: cache local sincronizado quando o gestor conecta Meta via OAuth. "
    "Pra forçar refresh dos accounts, gestor precisa reconectar via painel admin. "
    "Retorna: ad_account_id ('act_<numeric>'), account_name, business_id/name "
    "(NULL se personal), currency, timezone_name, account_status (Meta enum) "
    "+ account_status_label (PT-BR)."
)


@register_tool(
    name="meta_list_my_ad_accounts",
    description=_DESCRIPTION,
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
)
async def handler(_args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        accounts = await manager_meta_account_access.list_accounts_for_manager(conn, ctx.manager_id)
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
