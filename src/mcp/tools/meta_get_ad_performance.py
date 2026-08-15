# bucket: defer
"""meta_get_ad_performance — Performance por anúncio (ad) Meta (Sprint M.3).

Paridade com Google get_ad_performance. Bucket=defer (granular, gestor
pede após ver campaign + ad_set levels).
"""

from typing import Any
from uuid import UUID

from src.mcp.context import get_current
from src.mcp.tools._meta_performance import run_meta_level_performance
from src.mcp.tools._registry import register_tool

_DESCRIPTION = (
    "[DEFER] Performance por anúncio (ad) Meta Ads: spend, impressões, clicks, "
    "CTR, CPC, reach, frequency, purchases, purchases_value_brl, purchase_roas, "
    "leads. Inclui ad_set_id/name + campaign_id/name parents. "
    "Ordenado por spend desc entre os anúncios lidos — a resposta traz `truncated`: se vier true, o teto de paginacao cortou e o topo pode estar incompleto (veja `truncated_hint`). Filtros: limit (max 500). "
    "[Limitação] Metadata de entidade (effective_status, creative_id) NÃO vem: a "
    "Meta Insights API só serve métricas — esses campos vivem em /ads. Retorna "
    "anúncios de qualquer status; pra saber o status, consulte o Gerenciador."
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


async def meta_get_ad_performance(
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
        level="ad",
        operation_name="meta_get_ad_performance",
        manager_id=manager_id,
        session_id=session_id,
        ad_account_id=ad_account_id,
        date_range=date_range,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )


@register_tool(
    name="meta_get_ad_performance",
    description=_DESCRIPTION,
    input_schema=_INPUT_SCHEMA,
    bucket="defer",
)
async def handler(args: dict[str, Any]) -> dict[str, Any]:
    """MCP tool handler — pulls context from contextvars, delegates to core."""
    ctx = get_current()
    return await meta_get_ad_performance(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        ad_account_id=args["ad_account_id"],
        date_range=args.get("date_range"),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
        limit=args.get("limit", 100),
    )
