# bucket: always
"""meta_get_ad_performance — Performance por anúncio (ad) Meta (Sprint M.3).

Paridade com Google get_ad_performance. Bucket=defer (granular, gestor
pede após ver campaign + ad_set levels).
"""

from copy import deepcopy
from typing import Any
from uuid import UUID

from src.mcp.context import get_current
from src.mcp.tools._meta_performance import SCHEMA_PERFORMANCE_META, run_meta_level_performance
from src.mcp.tools._registry import register_tool
from src.meta_ads.metricas import CONTRATO_NA_DESCRIPTION

_DESCRIPTION = (
    "[CORE] Performance por anúncio (ad) Meta Ads, uma linha por anúncio. "
    + CONTRATO_NA_DESCRIPTION
    + " "
    "Inclui ad_set_id/name + campaign_id/name parents. "
    "Ordenado por spend desc **no servidor**, entao o topo devolvido E o topo real da conta; `truncated:true` significa que ficou cauda de MENOR gasto de fora, nao que o ranking esteja incompleto. Filtros: limit (max 500). "
    "[Limitação] Metadata de entidade (effective_status, creative_id) NÃO vem: a "
    "Meta Insights API só serve métricas. Retorna anúncios de qualquer status; "
    "pra ler status e criativo, use `meta_get_entities`."
)

_INPUT_SCHEMA: dict[str, Any] = deepcopy(SCHEMA_PERFORMANCE_META)


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
    bucket="always",
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
