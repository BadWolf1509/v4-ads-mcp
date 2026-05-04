"""Tool: get_recommendations - Google Ads recommendations pending for account."""

from typing import Any

from src.google_ads.queries._common import micros_to_currency
from src.google_ads.queries.recommendations import recommendations_query
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {
            "type": "string",
            "pattern": "^[0-9]{10}$",
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


_TYPE_PT = {
    "KEYWORD": "Adicionar palavra-chave",
    "ADD_AGE_GROUP_CRITERION": "Adicionar criterio de faixa etaria",
    "TEXT_AD": "Criar texto de anuncio",
    "CALLOUT_EXTENSION": "Adicionar extensao de chamada",
    "SITELINK_EXTENSION": "Adicionar extensao de sitelink",
    "ENHANCED_CPC_OPT_IN": "Ativar lance otimizado",
    "MAXIMIZE_CONVERSIONS_OPT_IN": "Migrar pra Maximizar conversoes",
    "MAXIMIZE_CLICKS_OPT_IN": "Migrar pra Maximizar clicks",
    "TARGET_CPA_OPT_IN": "Migrar pra Target CPA",
    "MAXIMIZE_CONVERSION_VALUE_OPT_IN": "Migrar pra Maximizar valor",
    "MOVE_UNUSED_BUDGET": "Mover orcamento nao usado",
    "FORECASTING_CAMPAIGN_BUDGET": "Aumentar orcamento da campanha",
    "RESPONSIVE_SEARCH_AD": "Criar anuncio responsivo",
}


def _row_formatter(row: Any) -> dict[str, Any]:
    rec = row.recommendation
    base = rec.impact.base_metrics
    pot = rec.impact.potential_metrics
    type_str = str(rec.type).split(".")[-1]
    return {
        "resource_name": rec.resource_name,
        "type": type_str,
        "type_pt": _TYPE_PT.get(type_str, type_str),
        "current_clicks": int(base.clicks),
        "current_impressions": int(base.impressions),
        "current_cost_brl": micros_to_currency(base.cost_micros),
        "potential_clicks": int(pot.clicks),
        "potential_impressions": int(pot.impressions),
        "potential_cost_brl": micros_to_currency(pot.cost_micros),
        "uplift_clicks": int(pot.clicks - base.clicks),
        "uplift_impressions": int(pot.impressions - base.impressions),
    }


@register_tool(
    name="get_recommendations",
    description=(
        "Recomendacoes pendentes do Google Ads pra conta: tipo, impacto estimado "
        "(clicks/impressoes/custo atual vs potencial), e identificador para "
        "aplicar/dispensar. Tipo e traduzido pra PT-BR quando reconhecido."
    ),
    input_schema=_SCHEMA,
)
async def get_recommendations(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    rows = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=recommendations_query(),
        row_formatter=_row_formatter,
        operation_name="get_recommendations",
        audit_this_call=True,  # sensitive: lists actionable changes
    )
    return {
        "customer_id": customer_id,
        "count": len(rows),
        "recommendations": rows,
    }
