# bucket: always
"""meta_get_campaign_performance — Performance por campanha Meta (Sprint M.3).

Paridade com Google get_campaign_performance: flat list ordenada por spend DESC.
Bucket=always (Pareto Meta top usage — primeira pergunta gestor V4).
"""

from typing import Any
from uuid import UUID

from src.mcp.context import get_current
from src.mcp.tools._meta_performance import run_meta_level_performance
from src.mcp.tools._registry import register_tool

_DESCRIPTION = (
    "[CORE] Performance por campanha Meta Ads: spend, impressões, clicks, CTR, "
    "CPC, reach, frequency, purchases, purchases_value_brl, purchase_roas, leads. "
    "Ordenado por spend desc **no servidor**, entao o topo devolvido E o topo real da conta; `truncated:true` significa que ficou cauda de MENOR gasto de fora, nao que o ranking esteja incompleto. Filtros: limit (max 500). "
    "Use meta_list_my_ad_accounts pra listar ad_account_ids disponíveis. "
    "[Limitação] Retorna campanhas de QUALQUER status (ACTIVE/PAUSED/ARCHIVED) e "
    "o status NÃO vem na resposta: a Meta Insights API não aceita effective_status "
    "nem em fields nem em filtering (é metadata de /campaigns). Portanto não dá "
    "pra filtrar por status nem aqui nem client-side — pra saber o status, consulte "
    "o Gerenciador de Anúncios. Campanha pausada com gasto no período APARECE aqui."
)

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ad_account_id": {
            "type": "string",
            "pattern": r"^act_\d+$",
            "description": (
                "Meta ad account ID (formato act_<numeric>). "
                "Use meta_list_my_ad_accounts pra descobrir IDs disponíveis."
            ),
        },
        "date_range": {
            "type": "string",
            "enum": [
                "TODAY",
                "YESTERDAY",
                "LAST_7_DAYS",
                "LAST_14_DAYS",
                "LAST_30_DAYS",
                "LAST_90_DAYS",
            ],
            "description": ("Preset. Default LAST_30_DAYS se start_date+end_date não fornecidos."),
        },
        "start_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
            "description": "Custom range start. Sobrescreve preset. Requires end_date.",
        },
        "end_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
            "description": "Custom range end. Sobrescreve preset. Requires start_date.",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 500,
            "default": 100,
            "description": "Max rows. Meta API cap = 500/page.",
        },
    },
    "required": ["ad_account_id"],
    "additionalProperties": False,
}


async def meta_get_campaign_performance(
    manager_id: UUID,
    session_id: UUID,
    *,
    ad_account_id: str,
    date_range: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Core logic — testable by integration tests.

    Wrapper fino sobre o núcleo compartilhado do trio (Task 3.3 dedup) —
    veja src/mcp/tools/_meta_performance.py::run_meta_level_performance.
    """
    return await run_meta_level_performance(
        level="campaign",
        operation_name="meta_get_campaign_performance",
        manager_id=manager_id,
        session_id=session_id,
        ad_account_id=ad_account_id,
        date_range=date_range,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )


@register_tool(
    name="meta_get_campaign_performance",
    description=_DESCRIPTION,
    input_schema=_INPUT_SCHEMA,
    bucket="always",
)
async def handler(args: dict[str, Any]) -> dict[str, Any]:
    """MCP tool handler — pulls context from contextvars, delegates to core."""
    ctx = get_current()
    return await meta_get_campaign_performance(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        ad_account_id=args["ad_account_id"],
        date_range=args.get("date_range"),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
        limit=args.get("limit", 100),
    )
