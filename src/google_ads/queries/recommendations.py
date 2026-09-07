"""Consultas GAQL + tabela de tipos das recomendacoes do Google Ads.

**A superficie que a GAQL aceita nao e a do proto (classe F87/F89).** Cada tipo
de recomendacao guarda seus numeros num campo de detalhe proprio
(`recommendation.campaign_budget_recommendation` e irmaos). O proto do SDK expoe
as FOLHAS desse campo (`google/ads/googleads/v24/resources/types/recommendation.py`
:575,580 — `current_budget_amount_micros`, `recommended_budget_amount_micros`),
mas a GAQL **nao** as expoe individualmente. Probado em 07/09 na conta
`1171969590` via `validate_gaql`:

    recommendation.campaign_budget_recommendation                    -> valid
    recommendation.campaign_budget_recommendation
        .current_budget_amount_micros                                -> Unrecognized fields

Seleciona-se a MENSAGEM; o SDK a popula; o Python le a folha do objeto. Quem
escrever a query olhando o proto erra.

`CAMPOS_DE_DETALHE` tem os 17 tipos que mexem em ORCAMENTO ou LANCE, extraidos do
enum (`google/ads/googleads/v24/enums/types/recommendation_type.py`, 55 tipos no
total) e nao de memoria. Os 17 campos de detalhe foram validados por
`validate_gaql` em 07/09, um a um e todos juntos; a linha viva da 1171969590
(`CAMPAIGN_BUDGET`, campanha 22922100363) devolveu
`current_budget_amount_micros: 50000000` e `recommended_budget_amount_micros:
180000000` — o aumento de 3,6x que ate 07/09 se aplicava sem preview nenhum.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from src.google_ads.queries._common import micros_to_currency
from src.google_ads.queries._gaql import gaql_string_literal

# Unidade de cada valor lido do detalhe:
#   brl    — campo `*_micros` de DINHEIRO; vira reais (micros / 1e6, 2 casas)
#   razao  — campo `*_micros` de RAZAO (ROAS); vira o numero puro, nunca "R$"
#   numero — ja e um numero direto (multiplicador)
#   texto  — resource name / string
Unidade = Literal["brl", "razao", "numero", "texto"]


@dataclass(frozen=True, slots=True)
class DetalheDoTipo:
    """Onde vive o numero de um tipo de recomendacao.

    `campo` e o campo de detalhe SELECIONAVEL na GAQL (a mensagem inteira).
    `atual_brl` / `recomendado_brl` sao caminhos dotted DENTRO dela para os dois
    valores monetarios da MESMA dimensao — sao eles que viram
    `current_amount_brl` / `recommended_amount_brl` no preview. Tipo que nao tem
    a dimensao (ou cujo valor e razao, nao dinheiro) deixa `None` e poe o que
    tiver em `outros`, cada item `(chave_de_saida, caminho_dotted, unidade)`.
    """

    campo: str
    atual_brl: str | None = None
    recomendado_brl: str | None = None
    outros: tuple[tuple[str, str, Unidade], ...] = field(default=())


# Os tres tipos de orcamento compartilham a mesma mensagem (CampaignBudgetRecommendation).
_ORCAMENTO = ("current_budget_amount_micros", "recommended_budget_amount_micros")
_ROAS_RECOMENDADO: tuple[tuple[str, str, Unidade], ...] = (
    ("target_roas_recomendado", "recommended_target_roas", "numero"),
)

CAMPOS_DE_DETALHE: dict[str, DetalheDoTipo] = {
    # --- orcamento: os unicos com atual E recomendado na mesma mensagem ---
    "CAMPAIGN_BUDGET": DetalheDoTipo("campaign_budget_recommendation", *_ORCAMENTO),
    "FORECASTING_CAMPAIGN_BUDGET": DetalheDoTipo(
        "forecasting_campaign_budget_recommendation", *_ORCAMENTO
    ),
    "MARGINAL_ROI_CAMPAIGN_BUDGET": DetalheDoTipo(
        "marginal_roi_campaign_budget_recommendation", *_ORCAMENTO
    ),
    "MOVE_UNUSED_BUDGET": DetalheDoTipo(
        "move_unused_budget_recommendation",
        "budget_recommendation.current_budget_amount_micros",
        "budget_recommendation.recommended_budget_amount_micros",
        (("orcamento_de_origem", "excess_campaign_budget", "texto"),),
    ),
    # --- opt-ins que trazem o orcamento que a estrategia nova exige ---
    "MAXIMIZE_CLICKS_OPT_IN": DetalheDoTipo(
        "maximize_clicks_opt_in_recommendation", None, "recommended_budget_amount_micros"
    ),
    "MAXIMIZE_CONVERSIONS_OPT_IN": DetalheDoTipo(
        "maximize_conversions_opt_in_recommendation", None, "recommended_budget_amount_micros"
    ),
    # --- alvos de CPA (dinheiro) ---
    "TARGET_CPA_OPT_IN": DetalheDoTipo(
        "target_cpa_opt_in_recommendation", None, "recommended_target_cpa_micros"
    ),
    "SET_TARGET_CPA": DetalheDoTipo(
        "set_target_cpa_recommendation", None, "recommended_target_cpa_micros"
    ),
    "FORECASTING_SET_TARGET_CPA": DetalheDoTipo(
        "forecasting_set_target_cpa_recommendation", None, "recommended_target_cpa_micros"
    ),
    "RAISE_TARGET_CPA": DetalheDoTipo(
        "raise_target_cpa_recommendation",
        "target_adjustment.current_average_target_micros",
        None,
        (
            (
                "multiplicador_recomendado",
                "target_adjustment.recommended_target_multiplier",
                "numero",
            ),
        ),
    ),
    "RAISE_TARGET_CPA_BID_TOO_LOW": DetalheDoTipo(
        "raise_target_cpa_bid_too_low_recommendation",
        "average_target_cpa_micros",
        None,
        (("multiplicador_recomendado", "recommended_target_multiplier", "numero"),),
    ),
    # --- alvos de ROAS (razao: nunca vira "R$") ---
    "TARGET_ROAS_OPT_IN": DetalheDoTipo(
        "target_roas_opt_in_recommendation",
        None,
        None,
        (
            ("target_roas_recomendado", "recommended_target_roas", "numero"),
            ("orcamento_exigido_brl", "required_campaign_budget_amount_micros", "brl"),
        ),
    ),
    "SET_TARGET_ROAS": DetalheDoTipo(
        "set_target_roas_recommendation", None, None, _ROAS_RECOMENDADO
    ),
    "FORECASTING_SET_TARGET_ROAS": DetalheDoTipo(
        "forecasting_set_target_roas_recommendation", None, None, _ROAS_RECOMENDADO
    ),
    "LOWER_TARGET_ROAS": DetalheDoTipo(
        "lower_target_roas_recommendation",
        None,
        None,
        (
            ("target_roas_atual", "target_adjustment.current_average_target_micros", "razao"),
            (
                "multiplicador_recomendado",
                "target_adjustment.recommended_target_multiplier",
                "numero",
            ),
        ),
    ),
    # --- os dois sem numero nenhum: a mensagem e VAZIA no v24 ---
    # Nao e omissao: `EnhancedCpcOptInRecommendation` e
    # `MaximizeConversionValueOptInRecommendation` nao declaram campo algum no
    # descriptor. O preview desses dois se apoia no contexto da campanha (ver
    # `campaign_context_query`) — e a estrategia de lance de hoje que eles trocam.
    "ENHANCED_CPC_OPT_IN": DetalheDoTipo("enhanced_cpc_opt_in_recommendation"),
    "MAXIMIZE_CONVERSION_VALUE_OPT_IN": DetalheDoTipo(
        "maximize_conversion_value_opt_in_recommendation"
    ),
}

# DERIVADO, nao enumerado de novo: a lista dos 17 vive num lugar so. Acrescentar
# um tipo a tabela acima ja o poe sob confirmacao.
TIPOS_QUE_CONFIRMAM: frozenset[str] = frozenset(CAMPOS_DE_DETALHE)


TYPE_PT = {
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
    # Forecasting variants (P3 dogfood F7 finding — FORECASTING_SET_TARGET_CPA missing)
    "FORECASTING_SET_TARGET_CPA": "Definir Target CPA previsto",
    "FORECASTING_SET_TARGET_ROAS": "Definir Target ROAS previsto",
    # Performance Max upgrades (Google pushes these aggressively in 2024+)
    "UPGRADE_LOCAL_CAMPAIGN_TO_PERFORMANCE_MAX": "Migrar Local pra Performance Max",
    "UPGRADE_SMART_SHOPPING_CAMPAIGN_TO_PERFORMANCE_MAX": "Migrar Smart Shopping pra Performance Max",
    "IMPROVE_PERFORMANCE_MAX_AD_STRENGTH": "Melhorar forca do Performance Max",
    # C2 — os que faltavam da familia de orcamento/lance. Sem traducao, o gestor
    # confirmaria uma mudanca de lance lendo so o enum em ingles.
    "MARGINAL_ROI_CAMPAIGN_BUDGET": "Ajustar orcamento pelo ROI marginal",
    "SET_TARGET_CPA": "Definir Target CPA",
    "SET_TARGET_ROAS": "Definir Target ROAS",
    "RAISE_TARGET_CPA": "Aumentar o Target CPA",
    "RAISE_TARGET_CPA_BID_TOO_LOW": "Aumentar o Target CPA (lance baixo demais)",
    "LOWER_TARGET_ROAS": "Reduzir o Target ROAS",
}


def recommendations_query(limit: int = 100) -> str:
    """All pending recommendations for the account.

    NOTE: Impact metrics (base_metrics.*, potential_metrics.*) intentionally
    omitted — they're selectable_with-restricted in v24 and depend on the
    recommendation type. Users can query specific types via run_gaql for
    detailed impact data.

    F98 — pede `limit + 1`: a linha extra é a sentinela que revela o corte. As
    recomendações escalam com o nº de ad_groups (`RESPONSIVE_SEARCH_AD_ASSET` e
    `KEYWORD` são por ad_group), então sem teto uma conta grande estoura o cap
    de token do MCP e a resposta inteira se perde.
    """
    return f"""
        SELECT
          recommendation.resource_name,
          recommendation.type,
          recommendation.dismissed
        FROM recommendation
        WHERE recommendation.dismissed = false
        LIMIT {limit + 1}
    """.strip()


def _campos_de_detalhe_selecionados() -> list[str]:
    """Os 17 campos de detalhe, ordenados — a lista sai da tabela, nao de uma copia."""
    return sorted({f"recommendation.{d.campo}" for d in CAMPOS_DE_DETALHE.values()})


def recommendation_detail_query(resource_name: str) -> str:
    """Uma recomendacao pelo resource_name, com tipo + o detalhe de todos os 17 tipos.

    **Sem join com `campaign` de proposito.** Selecionar `campaign.*` daqui faria
    um join implicito, e nao ha como medir (em 07/09 nenhuma conta do MCC tinha
    recomendacao de nivel CONTA viva) se isso derrubaria a linha de uma
    recomendacao sem campanha — que apareceria como "nao encontrada". O contexto
    da campanha vem de `campaign_context_query`, numa segunda ida que so o
    caminho de confirmacao paga.
    """
    campos = ",\n          ".join(
        [
            "recommendation.resource_name",
            "recommendation.type",
            "recommendation.campaign",
            *_campos_de_detalhe_selecionados(),
        ]
    )
    return f"""
        SELECT
          {campos}
        FROM recommendation
        WHERE recommendation.resource_name = {gaql_string_literal(resource_name)}
        LIMIT 1
    """.strip()


def campaign_context_query(campaign_id: str) -> str:
    """Estrategia de lance + orcamento diario de HOJE da campanha alvo.

    E o que o preview mostra quando o tipo nao carrega numero nenhum
    (`ENHANCED_CPC_OPT_IN`, `MAXIMIZE_CONVERSION_VALUE_OPT_IN`): a recomendacao
    troca a estrategia de lance, e a estrategia trocada e justamente esta.
    """
    if not campaign_id.isdigit():
        raise ValueError(f"campaign_id nao numerico: {campaign_id!r}")
    return f"""
        SELECT
          campaign.id,
          campaign.name,
          campaign.status,
          campaign.bidding_strategy_type,
          campaign_budget.amount_micros
        FROM campaign
        WHERE campaign.id = {campaign_id}
        LIMIT 1
    """.strip()


def _nome_do_enum(valor: Any) -> str:
    """proto-plus IntEnum -> nome; str continua str (mocks de teste)."""
    return str(valor.name) if hasattr(valor, "name") else str(valor)


def _ler(msg: Any, caminho: str) -> Any:
    """Le uma folha dotted DENTRO da mensagem de detalhe."""
    for parte in caminho.split("."):
        msg = getattr(msg, parte)
    return msg


def _converter(bruto: Any, unidade: Unidade) -> Any:
    if unidade == "brl":
        return micros_to_currency(int(bruto))
    if unidade == "razao":
        return round(int(bruto) / 1_000_000.0, 4)
    if unidade == "numero":
        return float(bruto)
    return str(bruto)


def id_da_campanha(resource_name: str) -> str | None:
    """`customers/1/campaigns/22922100363` -> `22922100363`; None se nao houver."""
    marcador = "/campaigns/"
    if marcador not in resource_name:
        return None
    cid = resource_name.rsplit(marcador, 1)[-1]
    return cid if cid.isdigit() else None


def parse_recommendation_detail_row(row: Any) -> dict[str, Any]:
    """Tipo + os numeros do detalhe daquele tipo, ja em BRL onde e dinheiro.

    Campo de detalhe de OUTRO tipo chega com o zero-value do proto (F145) — por
    isso a leitura e keyed pelo `recommendation.type`, nunca por "qual campo veio
    preenchido".
    """
    rec = row.recommendation
    tipo = _nome_do_enum(rec.type)
    spec = CAMPOS_DE_DETALHE.get(tipo)

    atual: float | None = None
    recomendado: float | None = None
    valores: dict[str, Any] = {}
    if spec is not None:
        detalhe = getattr(rec, spec.campo)
        if spec.atual_brl is not None:
            atual = micros_to_currency(int(_ler(detalhe, spec.atual_brl)))
        if spec.recomendado_brl is not None:
            recomendado = micros_to_currency(int(_ler(detalhe, spec.recomendado_brl)))
        for chave, caminho, unidade in spec.outros:
            valores[chave] = _converter(_ler(detalhe, caminho), unidade)

    campanha_rn = str(rec.campaign or "")
    return {
        "resource_name": str(rec.resource_name),
        "type": tipo,
        "type_pt": TYPE_PT.get(tipo),
        "campaign_resource_name": campanha_rn,
        "campaign_id": id_da_campanha(campanha_rn),
        "current_amount_brl": atual,
        "recommended_amount_brl": recomendado,
        "valores": valores,
    }


def parse_campaign_context_row(row: Any) -> dict[str, Any]:
    return {
        "campaign_id": str(row.campaign.id),
        "campaign_name": str(row.campaign.name),
        "status": _nome_do_enum(row.campaign.status),
        "bidding_strategy_type": _nome_do_enum(row.campaign.bidding_strategy_type),
        "daily_budget_brl": micros_to_currency(int(row.campaign_budget.amount_micros)),
    }
