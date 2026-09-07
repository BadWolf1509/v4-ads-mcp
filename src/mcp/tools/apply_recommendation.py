# bucket: defer
"""Tool: apply_recommendation — aplica uma recomendacao do Google Ads.

**Gate por TIPO (C2).** Ate 2026-09-07 a tool computava `classify(...)` e chamava
`run_recommendation_action` na linha seguinte: `risk.level` nao era lido em lugar
nenhum, `risk.reason` virava o campo cosmetico `auto_applied_reason`, e o schema
aceitava qualquer `recommendation_resource_name` sem olhar o tipo. Medido em
07/09 na conta 1171969590: uma chamada so aplicava R$ 50,00 -> R$ 180,00/dia
(3,6x) numa campanha viva, sem token, sem preview e sem nunca mostrar o numero —
enquanto o `update_campaign_budget`, que produz o MESMO efeito, sempre confirmou.

Agora a tool le o tipo (e o detalhe daquele tipo) por GAQL ANTES de decidir, e
ramifica em `risk.level`:

* tipo dos 17 que mexem em orcamento ou lance -> `create_pending` +
  `preview_envelope`, com os valores em BRL e com o contexto da campanha;
* qualquer outro tipo -> o caminho de antes (auto-aplica).
"""

from typing import Any

from src.db import connection
from src.google_ads.mutations import run_recommendation_action
from src.google_ads.queries.recommendations import (
    campaign_context_query,
    parse_campaign_context_row,
    parse_recommendation_detail_row,
    recommendation_detail_query,
)
from src.google_ads.reports import run_report
from src.governance.blast_radius import RiskLevel, classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._mutate_common import applied_envelope, error_envelope, preview_envelope
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "recommendation_resource_name": {
            "type": "string",
            "minLength": 10,
            "description": (
                "Resource name completo da recomendacao "
                "(ex: 'customers/1234567890/recommendations/abc123'). "
                "Use get_recommendations pra listar as pendentes."
            ),
        },
    },
    "required": ["customer_id", "recommendation_resource_name"],
    "additionalProperties": False,
}


def _rotulo(info: dict[str, Any]) -> str:
    pt = info["type_pt"]
    return f"{info['type']} ({pt})" if pt else str(info["type"])


def _delta_pct(atual: float | None, recomendado: float | None) -> float | None:
    if atual is None or recomendado is None or atual == 0:
        return None
    return round((recomendado - atual) / atual * 100, 2)


def _trecho_dos_valores(info: dict[str, Any], campanha: dict[str, Any] | None) -> str:
    """A parte do resumo que carrega os NUMEROS — ou, sem numero, o que sera trocado.

    Decisao de desenho: os dois tipos cuja mensagem de detalhe e vazia no v24
    (`ENHANCED_CPC_OPT_IN`, `MAXIMIZE_CONVERSION_VALUE_OPT_IN`) nao tem numero
    nenhum a mostrar. Confirmar sem ver nada util e quase tao ruim quanto nao
    confirmar, entao o preview mostra o que a recomendacao TROCA: a estrategia
    de lance e o orcamento diario que a campanha tem hoje.
    """
    atual = info["current_amount_brl"]
    recomendado = info["recommended_amount_brl"]
    delta = _delta_pct(atual, recomendado)
    partes: list[str] = []
    if atual is not None and recomendado is not None:
        variacao = f" (delta {delta:+.1f}%)" if delta is not None else ""
        partes.append(f"R$ {atual:.2f} -> R$ {recomendado:.2f}{variacao}")
    elif recomendado is not None:
        partes.append(f"valor proposto R$ {recomendado:.2f}")
    elif atual is not None:
        partes.append(f"valor atual R$ {atual:.2f}")
    partes += [f"{chave}={valor}" for chave, valor in sorted(info["valores"].items())]

    if partes:
        return "; ".join(partes)
    if campanha is not None:
        return (
            "a recomendacao nao traz valor numerico — ela TROCA a estrategia de lance, "
            f"hoje {campanha['bidding_strategy_type']} com orcamento de "
            f"R$ {campanha['daily_budget_brl']:.2f}/dia"
        )
    return "a recomendacao nao traz valor numerico e nao foi possivel ler a campanha alvo"


def _resumo(customer_id: str, info: dict[str, Any], campanha: dict[str, Any] | None) -> str:
    onde = (
        f"na campanha '{campanha['campaign_name']}' (id {campanha['campaign_id']})"
        if campanha is not None
        else f"na conta {customer_id}"
    )
    return (
        f"Aplicar recomendacao {_rotulo(info)} {onde}: "
        f"{_trecho_dos_valores(info, campanha)}. "
        f"Conta {customer_id}, recomendacao {info['resource_name']}."
    )


@register_tool(
    name="apply_recommendation",
    description=(
        "[DEFER] Aplica uma recomendacao pendente do Google Ads. O caminho depende do "
        "TIPO: recomendacao que mexe em ORCAMENTO ou LANCE (CAMPAIGN_BUDGET, "
        "FORECASTING_CAMPAIGN_BUDGET, TARGET_CPA_OPT_IN, SET_TARGET_ROAS e mais 13) "
        "devolve preview com confirmation_token — valor atual, valor recomendado e a "
        "campanha atingida — e so aplica via apply_change; mesma regra do "
        "update_campaign_budget, que produz o mesmo efeito. Os demais tipos "
        "(keyword, sitelink, RSA...) seguem auto-aplicando. Use get_recommendations "
        "primeiro para listar as disponiveis."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def apply_recommendation(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    rec_resource = args["recommendation_resource_name"]

    async def _consulta(gaql: str, parser: Any) -> list[dict[str, Any]]:
        return await run_report(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            query=gaql,
            row_formatter=parser,
            operation_name="apply_recommendation_lookup",
        )

    linhas = await _consulta(
        recommendation_detail_query(rec_resource), parse_recommendation_detail_row
    )
    if not linhas:
        return error_envelope(
            "apply_recommendation",
            f"Recomendacao {rec_resource} nao encontrada na conta {customer_id} "
            "(ja aplicada, dispensada ou expirada). Use get_recommendations pra "
            "listar as pendentes.",
            customer_id=customer_id,
        )
    info = linhas[0]

    risk = classify(
        operation="apply_recommendation",
        params={"target_count": 1, "recommendation_type": info["type"]},
    )
    payload = {
        "recommendation_resource_name": rec_resource,
        "__target_count__": 1,
    }

    if risk.level is not RiskLevel.CONFIRM:
        summary = f"Aplicar recomendacao {_rotulo(info)} {rec_resource} na conta {customer_id}."
        result = await run_recommendation_action(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="apply_recommendation",
            payload=payload,
        )
        return applied_envelope(
            "apply_recommendation",
            customer_id,
            summary,
            applied_count=result["applied_count"],
            provider_request_id=result["provider_request_id"],
            auto_applied_reason=risk.reason,
            recommendation_type=info["type"],
            type_pt=info["type_pt"],
        )

    # Caminho de confirmacao. A segunda ida a API so acontece aqui — e so quando a
    # recomendacao e de campanha (as de nivel conta nao tem `recommendation.campaign`).
    # Lista vazia (campanha REMOVED, por exemplo) degrada pra `campanha: null`; so
    # excecao propaga, e propagar e o lado seguro porque nada foi escrito ainda.
    campanha: dict[str, Any] | None = None
    if info["campaign_id"] is not None:
        contexto = await _consulta(
            campaign_context_query(info["campaign_id"]), parse_campaign_context_row
        )
        campanha = contexto[0] if contexto else None

    summary = _resumo(customer_id, info, campanha)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="apply_recommendation",
            payload=payload,
            blast_summary=summary,
        )
    return preview_envelope(
        "apply_recommendation",
        customer_id,
        summary,
        token,
        confirmation_reason=risk.reason,
        recommendation_type=info["type"],
        type_pt=info["type_pt"],
        current_amount_brl=info["current_amount_brl"],
        recommended_amount_brl=info["recommended_amount_brl"],
        delta_pct=_delta_pct(info["current_amount_brl"], info["recommended_amount_brl"]),
        valores=info["valores"],
        campanha=campanha,
    )
