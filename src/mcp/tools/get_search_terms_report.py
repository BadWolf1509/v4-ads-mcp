# bucket: defer
"""Tool: get_search_terms_report - actual search terms that triggered ads."""

from typing import Any

from src.google_ads.queries._common import (
    arredondado,
    em_moeda,
    micros_to_currency,
    razao,
)
from src.google_ads.queries.tactical import search_terms_query
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._common import aplicar_limite, janela_da_conta, propriedades_de_data
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        **propriedades_de_data(),
        "limit": {"type": "integer", "minimum": 1, "maximum": 10000, "default": 50},
        "min_cost_brl": {
            "type": "number",
            "minimum": 0,
            "description": (
                "Custo minimo em BRL no periodo. Filtra server-side (GAQL WHERE). "
                "Omitir = sem filtro de custo."
            ),
        },
        "min_clicks": {
            "type": "integer",
            "minimum": 0,
            "description": (
                "Clicks minimos no periodo. Filtra server-side (GAQL WHERE). "
                "Omitir = sem filtro de clicks."
            ),
        },
        "min_conversions": {
            "type": "number",
            "minimum": 0,
            "description": (
                "Conversoes minimas no periodo (exclusive: > valor). Filtra server-side (GAQL WHERE). "
                "Use 0 pra exigir pelo menos 1 conversao. Omitir = sem filtro."
            ),
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


def _row_formatter(row: Any) -> dict[str, Any]:
    m = row.metrics
    impr = int(m.impressions)
    clicks = int(m.clicks)
    cost_micros = int(m.cost_micros)
    return {
        "search_term": row.search_term_view.search_term,
        "status": row.search_term_view.status.name,
        "ad_group_id": str(row.ad_group.id),
        "ad_group_name": row.ad_group.name,
        "campaign_id": str(row.campaign.id),
        "campaign_name": row.campaign.name,
        "impressions": impr,
        "clicks": clicks,
        "cost_brl": micros_to_currency(cost_micros),
        "conversions": round(float(m.conversions), 2),
        "conversions_value_brl": round(float(m.conversions_value), 2),
        "ctr": arredondado(razao(clicks, impr), 4),
        "cpc_brl": em_moeda(razao(cost_micros, clicks)),
    }


@register_tool(
    name="get_search_terms_report",
    description=(
        "[DEFER] Termos de busca reais que dispararam anuncios. Status indica se ja foi "
        "adicionado como palavra-chave (ADDED) ou negativa (EXCLUDED) ou nem um "
        "nem outro (NONE). Util pra encontrar negativas pra adicionar e termos "
        "performantes pra promover. `truncated: true` avisa que a conta tinha MAIS "
        "termos do que o limit (default 50, baixo) e a lista foi cortada no topo de "
        "gasto — a cauda de termos ruins costuma estar ABAIXO do corte, entao suba o "
        "limit ou use min_cost_brl/min_clicks antes de concluir que nao ha o que "
        "negativar."
        " Razao com denominador zero vem null (indefinida), nao 0."
        " filters_applied diz o recorte que a query aplicou."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def get_search_terms_report(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    start, end, _ = await janela_da_conta(ctx, args, customer_id)
    limit = args.get("limit", 50)
    gaql, filtros = search_terms_query(
        start,
        end,
        limit,
        min_cost_brl=args.get("min_cost_brl"),
        min_clicks=args.get("min_clicks"),
        min_conversions=args.get("min_conversions"),
    )
    rows = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=gaql,
        row_formatter=_row_formatter,
        operation_name="get_search_terms_report",
    )
    # A consulta pediu `limit + 1`; a linha extra e a sentinela que revela o
    # corte e nao pode chegar ao gestor.
    rows, truncado = aplicar_limite(rows, limit)
    return {
        "customer_id": customer_id,
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "filters_applied": filtros,
        "rows": rows,
        "truncated": truncado,
    }
