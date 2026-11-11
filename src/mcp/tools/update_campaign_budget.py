# bucket: defer
"""Tool: update_campaign_budget - update a campaign's daily budget. Always confirms."""

from typing import Any

from src.google_ads.orcamento_compartilhado import montar_bloco
from src.google_ads.preflight import buscar_orcamento_da_campanha
from src.google_ads.queries._common import (
    arredondado,
    brl_para_micros,
    micros_to_currency,
    percentual,
    razao,
)
from src.google_ads.queries.ad_schedule import (
    campaigns_on_budgets_query,
    parse_campaign_on_budget_row,
)
from src.google_ads.reports import run_report
from src.governance.blast_radius import classify
from src.mcp.context import get_current
from src.mcp.tools._mutate_common import emitir_preview, error_envelope
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "campaign_id": {"type": "string", "pattern": "^[0-9]+$"},
        "new_daily_budget_brl": {
            "type": "number",
            "exclusiveMinimum": 0,
            "description": "Novo orcamento diario em BRL (ex: 150.50).",
        },
    },
    "required": ["customer_id", "campaign_id", "new_daily_budget_brl"],
    "additionalProperties": False,
}


async def _bloco_de_orcamento_compartilhado(
    consulta: Any, info: dict[str, Any], campaign_id: str, amount_brl: float
) -> dict[str, Any]:
    """Espelha `update_ad_schedule._blocos_de_orcamento_compartilhado` (spec §4.3): avisa, nao recusa.

    As chaves sao as MESMAS da outra tool de proposito — quem aprendeu a ler o aviso
    numa reconhece na outra. Duas divergencias deliberadas, e so estas:

    * o preview expoe `shared_budget` (dict|None), nao `shared_budgets` (lista):
      esta tool escreve em UM recurso orcamento, entao lista de no maximo um
      elemento seria ruido;
    * o texto do `warning_pt` — o mecanismo e outro. Desligar faixa de horario
      REALOCA gasto entre as irmas; mudar o valor do orcamento ATINGE direto o teto
      diario de todas elas.
    """
    rn = info["campaign_budget_resource_name"]
    # `campaigns_on_budgets_query` ja filtra `campaign.status != 'REMOVED'` server-side.
    todas = await consulta(
        campaigns_on_budgets_query(budget_resource_names=[rn]),
        parse_campaign_on_budget_row,
    )
    # No `update_ad_schedule` o "lote" e a lista `campaign_ids`; aqui e a campanha
    # unica que o gestor nomeou. Fica vazio se ela for REMOVED — a query so devolve viva.
    return montar_bloco(
        budget_id=info["budget_id"],
        budget_resource_name=rn,
        amount_brl=amount_brl,
        irmas=todas,
        no_lote=lambda cid: cid == campaign_id,
        sufixo_aviso=(
            "Mudar o valor aqui "
            "ATINGE todas elas: a mutacao e no recurso ORCAMENTO, nao na campanha "
            "nomeada no resumo — as irmas fora do lote passam a dividir o valor NOVO. "
            "Como a verba se reparte entre elas e pacing do Google — nao ha como "
            "medir por API."
        ),
    )


@register_tool(
    name="update_campaign_budget",
    description=(
        "[DEFER] Atualiza o orcamento diario de uma campanha. Sempre exige confirmacao "
        "via apply_change (mudancas de orcamento sao sensiveis - spec §7.1). "
        "Retorna preview com valor atual + novo + delta percentual. A mutacao e no "
        "recurso ORCAMENTO, nao na campanha: quando ele e do portfolio "
        "(campaign_budget.explicitly_shared), o preview traz `shared_budget` com as "
        "campanhas irmas que a mudanca ATINGE alem da nomeada — avisa, nao recusa. "
        "Orcamento exclusivo devolve `shared_budget: null`."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def update_campaign_budget(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    campaign_id = args["campaign_id"]
    new_amount_brl = float(args["new_daily_budget_brl"])
    new_amount_micros = brl_para_micros(new_amount_brl)

    async def _consulta(gaql: str, parser: Any) -> list[dict[str, Any]]:
        return await run_report(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            query=gaql,
            row_formatter=parser,
            operation_name="update_campaign_budget_lookup",
        )

    # Resolve current budget + resource name via GAQL.
    info = await buscar_orcamento_da_campanha(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        campaign_id=campaign_id,
    )
    if info is None:
        return error_envelope(
            "update_campaign_budget",
            f"Campanha {campaign_id} nao encontrada na conta {customer_id}.",
            customer_id=customer_id,
        )

    current_micros = info["current_amount_micros"]
    current_brl = micros_to_currency(current_micros)
    delta_pct = percentual(razao(new_amount_micros - current_micros, current_micros))

    risk = classify(
        operation="update_campaign_budget",
        params={"target_count": 1, "delta_pct": delta_pct},
    )

    payload = {
        "campaign_budget_resource_name": info["campaign_budget_resource_name"],
        "new_amount_micros": new_amount_micros,
        "__target_count__": 1,
    }
    delta_txt = (
        f"delta {delta_pct:+.1f}%"
        if delta_pct is not None
        else "variacao indefinida: o orcamento atual e zero"
    )
    summary = (
        f"Orcamento de '{info['campaign_name']}' (id {campaign_id}): "
        f"R$ {current_brl} -> R$ {new_amount_brl:.2f} "
        f"({delta_txt})."
    )

    # A segunda ida a API so acontece quando ha portfolio para declarar.
    shared_budget = (
        await _bloco_de_orcamento_compartilhado(_consulta, info, campaign_id, current_brl)
        if info["explicitly_shared"]
        else None
    )
    if shared_budget is not None:
        # `apply_change` reexibe o `blast_summary`, nao o envelope do dry-run: se o
        # aviso vivesse so no `shared_budget`, quem confirma dez minutos depois leria
        # de novo o nome de UMA campanha e nada sobre as irmas.
        summary += (
            f" ATENCAO: orcamento COMPARTILHADO {shared_budget['budget_id']} — a mudanca "
            f"atinge mais {len(shared_budget['campaigns_outside_batch'])} campanha(s) "
            f"({shared_budget['ativas_fora_do_lote']} ativa(s)) alem desta."
        )

    # Budget changes are always classify=CONFIRM per blast_radius rules
    return await emitir_preview(
        ctx,
        operation="update_campaign_budget",
        customer_id=customer_id,
        payload=payload,
        resumo=summary,
        risk=risk,
        current_amount_brl=current_brl,
        new_amount_brl=new_amount_brl,
        delta_pct=arredondado(delta_pct, 2),
        shared_budget=shared_budget,
    )
