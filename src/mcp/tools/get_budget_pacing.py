# bucket: defer
"""Tool: get_budget_pacing - per-campaign budget vs MTD spend + projection."""

from typing import Any

from src.google_ads.account_clock import resolve_account_today
from src.google_ads.pacing import projetar_linhas, projetar_orcamentos
from src.google_ads.queries._common import micros_to_currency
from src.google_ads.queries.overview import (
    budget_pacing_hoje_query,
    budget_pacing_orcamentos_query,
    budget_pacing_query,
)
from src.google_ads.reports import run_report
from src.janelas import janela_do_preset
from src.mcp.context import get_current
from src.mcp.tools._common import aplicar_limite
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {
            "type": "string",
            "pattern": "^[0-9]{10}$",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 1000,
            "default": 100,
            "description": (
                "Máximo de campanhas retornadas, das que MAIS gastaram no mes. "
                "truncated:true se exceder."
            ),
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


def _row_formatter(row: Any) -> dict[str, Any]:
    return {
        "campaign_id": str(row.campaign.id),
        "campaign_name": row.campaign.name,
        "daily_budget_brl": micros_to_currency(row.campaign_budget.amount_micros),
        "delivery_method": row.campaign_budget.delivery_method.name,
        "budget_id": str(row.campaign_budget.id),
        "budget_name": row.campaign_budget.name,
        "orcamento_compartilhado": bool(row.campaign_budget.explicitly_shared),
        "cost_micros": int(row.metrics.cost_micros),
    }


def _row_formatter_hoje(row: Any) -> dict[str, Any]:
    return {"campaign_id": str(row.campaign.id), "cost_micros": int(row.metrics.cost_micros)}


def _row_formatter_orcamento(row: Any) -> dict[str, Any]:
    return {"budget_id": str(row.campaign_budget.id), "cost_micros": int(row.metrics.cost_micros)}


async def _gasto_por(
    chave: str,
    query: str,
    row_formatter: Any,
    *,
    customer_id: str,
) -> dict[str, int]:
    ctx = get_current()
    gasto: dict[str, int] = {}
    for r in await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=row_formatter,
        operation_name="get_budget_pacing",
    ):
        gasto[r[chave]] = gasto.get(r[chave], 0) + r["cost_micros"]
    return gasto


@register_tool(
    name="get_budget_pacing",
    description=(
        "[DEFER] Por campanha ativa: orcamento diario, gasto no mes ATE ONTEM "
        "(`spent_mtd_brl`, dias fechados), projecao de fim de mes pela media dos dias "
        "fechados, % consumido do orcamento mensal, e o gasto parcial de hoje em "
        "`gasto_hoje_brl` — dia ainda aberto, fora da projecao; serve de sinal de "
        "estouro no dia. No dia 1 nao ha dia fechado: a janela e so hoje "
        "(`inclui_dia_corrente: true`) e a projecao vem null. `days_elapsed` conta os "
        "dias fechados; `days_remaining` inclui hoje. ORCAMENTO COMPARTILHADO "
        "(`orcamento_compartilhado: true`): a campanha nao tem orcamento proprio, entao "
        "os dois percentuais dela vem null e o ritmo esta em `orcamentos_compartilhados`, "
        "um por orcamento, com o gasto lido do proprio orcamento — inclui campanha pausada "
        "ou fora da lista, entao pode passar da soma das campanhas listadas. Nao some "
        "`daily_budget_brl` das campanhas: as que dividem orcamento repetem o mesmo valor. "
        "Util pra ver no inicio do dia se alguma campanha esta acelerada/lenta demais. "
        "Ordenado por gasto no mes desc; limit (default 100, max 1000) corta a cauda e "
        "`truncated:true` avisa."
        " Razao com denominador zero vem null (indefinida), nao 0."
        " filters_applied diz o recorte que a query aplicou."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def get_budget_pacing(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    limit = args.get("limit", 100)
    today = await resolve_account_today(customer_id)
    inicio, fim = janela_do_preset("THIS_MONTH", today=today)
    gaql, filtros = budget_pacing_query(inicio, fim, limit=limit)
    rows = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=gaql,
        row_formatter=_row_formatter,
        operation_name="get_budget_pacing",
    )
    # F98 — a sentinela é uma campanha a mais e não pode entrar na projeção.
    rows, truncated = aplicar_limite(rows, limit)
    inclui_dia_corrente = fim == today
    gasto_hoje: dict[str, int] = {}
    if rows and not inclui_dia_corrente:
        ids = list(dict.fromkeys(r["campaign_id"] for r in rows))
        gaql_hoje, _ = budget_pacing_hoje_query(today, ids)
        gasto_hoje = await _gasto_por(
            "campaign_id", gaql_hoje, _row_formatter_hoje, customer_id=customer_id
        )
    compartilhados = list(
        dict.fromkeys(r["budget_id"] for r in rows if r["orcamento_compartilhado"])
    )
    orc_janela: dict[str, int] = {}
    orc_hoje: dict[str, int] = {}
    if compartilhados:
        gaql_orc, _ = budget_pacing_orcamentos_query(inicio, fim, compartilhados)
        orc_janela = await _gasto_por(
            "budget_id", gaql_orc, _row_formatter_orcamento, customer_id=customer_id
        )
        if not inclui_dia_corrente:
            gaql_orc_hoje, _ = budget_pacing_orcamentos_query(today, today, compartilhados)
            orc_hoje = await _gasto_por(
                "budget_id", gaql_orc_hoje, _row_formatter_orcamento, customer_id=customer_id
            )
    return {
        "customer_id": customer_id,
        "as_of": today.isoformat(),
        "period": {"from": inicio.isoformat(), "to": fim.isoformat()},
        "inclui_dia_corrente": inclui_dia_corrente,
        "filters_applied": filtros,
        "truncated": truncated,
        "campaigns": projetar_linhas(rows, gasto_hoje, today=today),
        "orcamentos_compartilhados": projetar_orcamentos(rows, orc_janela, orc_hoje, today=today),
    }
