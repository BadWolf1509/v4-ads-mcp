# bucket: defer
"""Tool: update_campaign_budget - update a campaign's daily budget. Always confirms."""

from typing import Any

from src.db import connection
from src.google_ads.queries._common import micros_to_currency
from src.google_ads.queries.ad_schedule import (
    campaigns_on_budgets_query,
    parse_campaign_on_budget_row,
)
from src.google_ads.reports import run_report
from src.governance.blast_radius import classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._mutate_common import error_envelope, preview_envelope
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


def _row_formatter(row: Any) -> dict[str, Any]:
    return {
        "campaign_budget_resource_name": row.campaign_budget.resource_name,
        "current_amount_micros": int(row.campaign_budget.amount_micros),
        "campaign_name": row.campaign.name,
        "budget_id": str(row.campaign_budget.id),
        # C1: sem este campo a tool escreve no recurso ORCAMENTO nomeando uma campanha
        # so. Proto-plus devolve o zero-value do campo nao selecionado (F145), entao
        # tirar `explicitly_shared` da GAQL apagaria o aviso em silencio.
        "explicitly_shared": bool(row.campaign_budget.explicitly_shared),
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
    dentro = [c["campaign_id"] for c in todas if c["campaign_id"] == campaign_id]
    fora = [
        {
            "campaign_id": c["campaign_id"],
            "campaign_name": c["campaign_name"],
            "status": c["status"],
        }
        for c in todas
        if c["campaign_id"] != campaign_id
    ]
    ativas = sum(1 for c in todas if c["status"] == "ENABLED")
    ativas_fora_do_lote = sum(1 for c in fora if c["status"] == "ENABLED")
    return {
        "budget_id": info["budget_id"],
        "budget_resource_name": rn,
        "explicitly_shared": True,
        "amount_brl": amount_brl,
        "campaigns_in_batch": dentro,
        "campaigns_outside_batch": fora,
        "ativas_fora_do_lote": ativas_fora_do_lote,
        "warning_pt": (
            f"Orcamento compartilhado {info['budget_id']} (R$ {amount_brl:.2f}/dia) "
            f"e de {len(todas)} campanha(s), {ativas} ativa(s); {len(dentro)} no lote, "
            f"{len(fora)} fora ({ativas_fora_do_lote} ativa(s)). Mudar o valor aqui "
            "ATINGE todas elas: a mutacao e no recurso ORCAMENTO, nao na campanha "
            "nomeada no resumo — as irmas fora do lote passam a dividir o valor NOVO. "
            "Como a verba se reparte entre elas e pacing do Google — nao ha como "
            "medir por API."
        ),
    }


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
    new_amount_micros = int(new_amount_brl * 1_000_000)

    # Resolve current budget + resource name via GAQL.
    # `campaign_budget.id` e `.explicitly_shared` sao superficie ja probada por
    # `validate_gaql` em 02/09 (ver docstring de src/google_ads/queries/ad_schedule.py).
    query = f"""
        SELECT
          campaign.id,
          campaign.name,
          campaign_budget.id,
          campaign_budget.resource_name,
          campaign_budget.explicitly_shared,
          campaign_budget.amount_micros
        FROM campaign
        WHERE campaign.id = {campaign_id}
        LIMIT 1
    """.strip()

    async def _consulta(gaql: str, parser: Any) -> list[dict[str, Any]]:
        return await run_report(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            query=gaql,
            row_formatter=parser,
            operation_name="update_campaign_budget_lookup",
        )

    rows = await _consulta(query, _row_formatter)
    if not rows:
        return error_envelope(
            "update_campaign_budget",
            f"Campanha {campaign_id} nao encontrada na conta {customer_id}.",
            customer_id=customer_id,
        )

    info = rows[0]
    current_micros = info["current_amount_micros"]
    current_brl = micros_to_currency(current_micros)
    delta_pct = (
        ((new_amount_micros - current_micros) / current_micros * 100) if current_micros else 0.0
    )

    risk = classify(
        operation="update_campaign_budget",
        params={"target_count": 1, "delta_pct": delta_pct},
    )

    payload = {
        "campaign_budget_resource_name": info["campaign_budget_resource_name"],
        "new_amount_micros": new_amount_micros,
        "__target_count__": 1,
    }
    summary = (
        f"Orcamento de '{info['campaign_name']}' (id {campaign_id}): "
        f"R$ {current_brl} -> R$ {new_amount_brl:.2f} "
        f"(delta {delta_pct:+.1f}%)."
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
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="update_campaign_budget",
            payload=payload,
            blast_summary=summary,
        )
    return preview_envelope(
        "update_campaign_budget",
        customer_id,
        summary,
        token,
        confirmation_reason=risk.reason,
        current_amount_brl=current_brl,
        new_amount_brl=new_amount_brl,
        delta_pct=round(delta_pct, 2),
        shared_budget=shared_budget,
    )
