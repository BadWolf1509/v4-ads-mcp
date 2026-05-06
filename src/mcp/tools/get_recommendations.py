"""Tool: get_recommendations - Google Ads recommendations pending for account."""

from typing import Any

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
    "CALLOUT_ASSET": "Adicionar asset de chamada",
    "SITELINK_EXTENSION": "Adicionar extensao de sitelink",
    "SITELINK_ASSET": "Adicionar asset de sitelink",
    "ENHANCED_CPC_OPT_IN": "Ativar lance otimizado",
    "SEARCH_PARTNERS_OPT_IN": "Ativar parceiros de pesquisa",
    "MAXIMIZE_CONVERSIONS_OPT_IN": "Migrar pra Maximizar conversoes",
    "MAXIMIZE_CLICKS_OPT_IN": "Migrar pra Maximizar clicks",
    "TARGET_CPA_OPT_IN": "Migrar pra Target CPA",
    "TARGET_ROAS_OPT_IN": "Migrar pra Target ROAS",
    "MAXIMIZE_CONVERSION_VALUE_OPT_IN": "Migrar pra Maximizar valor",
    "PERFORMANCE_MAX_OPT_IN": "Migrar pra Performance Max",
    "MOVE_UNUSED_BUDGET": "Mover orcamento nao usado",
    "FORECASTING_CAMPAIGN_BUDGET": "Aumentar orcamento da campanha",
    "CAMPAIGN_BUDGET": "Ajustar orcamento da campanha",
    "RESPONSIVE_SEARCH_AD": "Criar anuncio responsivo",
    "RESPONSIVE_SEARCH_AD_ASSET": "Adicionar asset em RSA",
    "RESPONSIVE_SEARCH_AD_IMPROVE_AD_STRENGTH": "Melhorar forca do RSA",
    "DYNAMIC_IMAGE_EXTENSION_OPT_IN": "Ativar imagens dinamicas",
    "USE_BROAD_MATCH_KEYWORD": "Usar correspondencia ampla",
    "DISPLAY_EXPANSION_OPT_IN": "Ativar expansao display",
    "LEAD_FORM_ASSET": "Adicionar formulario de leads",
    "IMPROVE_GOOGLE_TAG_COVERAGE": "Melhorar cobertura da Google Tag",
}


def _row_formatter(row: Any) -> dict[str, Any]:
    rec = row.recommendation
    # proto-plus IntEnum: str(v) returns the int as string ("29"); .name gives "SITELINK_ASSET".
    # Fall back to str() for plain strings (used by unit-test mocks).
    rec_type = rec.type
    type_str = rec_type.name if hasattr(rec_type, "name") else str(rec_type)
    return {
        "resource_name": rec.resource_name,
        "type": type_str,
        "type_pt": _TYPE_PT.get(type_str, type_str),
    }


@register_tool(
    name="get_recommendations",
    description=(
        "Recomendacoes pendentes do Google Ads pra conta: tipo (com nome em PT-BR "
        "quando reconhecido) e resource_name pra aplicar via apply_recommendation "
        "ou dispensar via dismiss_recommendation. Para ver impacto detalhado de "
        "uma recomendacao especifica, use run_gaql filtrando por recommendation.type."
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
