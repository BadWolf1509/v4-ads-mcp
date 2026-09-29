# bucket: defer
"""Tool: get_budget_pacing - per-campaign budget vs MTD spend + projection."""

from datetime import date
from typing import Any

from src.google_ads.account_clock import resolve_account_today
from src.google_ads.queries._common import arredondado, micros_to_currency, percentual, razao
from src.google_ads.queries.overview import (
    budget_pacing_hoje_query,
    budget_pacing_orcamentos_query,
    budget_pacing_query,
)
from src.google_ads.reports import run_report
from src.janelas import janela_do_preset
from src.mcp.context import get_current
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


def _calendario(today: date) -> tuple[int, int, int]:
    """(dias do mes, dias fechados, dias restantes) no dia `today` da conta.

    F199: fechados sao os `today.day - 1` dias ate ontem; os restantes incluem hoje.
    """
    if today.month == 12:
        next_month_first = today.replace(year=today.year + 1, month=1, day=1)
    else:
        next_month_first = today.replace(month=today.month + 1, day=1)
    days_in_month = (next_month_first - today.replace(day=1)).days
    dias_fechados = today.day - 1
    return days_in_month, dias_fechados, days_in_month - dias_fechados


def _ritmo(mtd: float, daily_budget: float, *, today: date) -> dict[str, Any]:
    """Projecao pelos dias fechados e os dois percentuais contra o orcamento do mes."""
    days_in_month, dias_fechados, _ = _calendario(today)
    daily_avg = razao(mtd, dias_fechados)
    projected = arredondado(None if daily_avg is None else daily_avg * days_in_month, 2)
    budget_monthly = round(daily_budget * days_in_month, 2)
    return {
        "monthly_budget_brl": budget_monthly,
        "projected_monthly_brl": projected,
        "spent_pct_of_monthly_budget": arredondado(percentual(razao(mtd, budget_monthly)), 1),
        "projection_vs_budget_pct": arredondado(percentual(razao(projected, budget_monthly)), 1),
    }


def _project(
    rows: list[dict[str, Any]],
    gasto_hoje_micros: dict[str, int] | None = None,
    *,
    today: date,
) -> list[dict[str, Any]]:
    """Agrega o gasto por campanha e projeta o fim do mes pelos dias FECHADOS.

    F141: `today` e o dia corrente NO FUSO DA CONTA, vindo do chamador. Com o
    dia UTC, a projecao do ultimo dia do mes saia 30x entre 21h e meia-noite.

    F199: `rows` traz o gasto da janela `THIS_MONTH` — ate ontem, os `today.day - 1`
    dias fechados. A projecao e a media deles vezes os dias do mes; no dia 1 nao ha
    dia fechado, e a razao sem denominador vem `None`. O gasto de hoje, parcial, vem
    em `gasto_hoje_micros` e so e ecoado: no dia 1 ele e o proprio gasto da janela.

    Orcamento compartilhado: a campanha nao tem orcamento proprio, entao os dois
    percentuais vem `None` — compara-la com o orcamento inteiro dizia 85% e 9% para duas
    campanhas que juntas estavam em 94,6%. O percentual dela esta em
    `orcamentos_compartilhados` (`_projeta_orcamentos`).
    """
    _, dias_fechados, days_remaining = _calendario(today)

    by_campaign: dict[str, dict[str, Any]] = {}
    for r in rows:
        cid = r["campaign_id"]
        if cid not in by_campaign:
            by_campaign[cid] = {
                "campaign_id": cid,
                "campaign_name": r["campaign_name"],
                "daily_budget_brl": r["daily_budget_brl"],
                "delivery_method": r["delivery_method"],
                "budget_id": r["budget_id"],
                "orcamento_compartilhado": r["orcamento_compartilhado"],
                "cost_micros_total": 0,
            }
        by_campaign[cid]["cost_micros_total"] += r["cost_micros"]

    out: list[dict[str, Any]] = []
    for c in by_campaign.values():
        mtd = micros_to_currency(c["cost_micros_total"])
        hoje_micros = (
            c["cost_micros_total"]
            if dias_fechados == 0
            else (gasto_hoje_micros or {}).get(c["campaign_id"], 0)
        )
        ritmo = _ritmo(mtd, c["daily_budget_brl"], today=today)
        if c["orcamento_compartilhado"]:
            ritmo["spent_pct_of_monthly_budget"] = None
            ritmo["projection_vs_budget_pct"] = None
        out.append(
            {
                "campaign_id": c["campaign_id"],
                "campaign_name": c["campaign_name"],
                "daily_budget_brl": c["daily_budget_brl"],
                "budget_id": c["budget_id"],
                "orcamento_compartilhado": c["orcamento_compartilhado"],
                "spent_mtd_brl": mtd,
                "gasto_hoje_brl": micros_to_currency(hoje_micros),
                "spent_pct_of_monthly_budget": ritmo["spent_pct_of_monthly_budget"],
                "days_elapsed": dias_fechados,
                "days_remaining": days_remaining,
                "projected_monthly_brl": ritmo["projected_monthly_brl"],
                "projection_vs_budget_pct": ritmo["projection_vs_budget_pct"],
                "delivery_method": c["delivery_method"],
            }
        )
    return sorted(out, key=lambda x: -x["spent_mtd_brl"])


def _projeta_orcamentos(
    rows: list[dict[str, Any]],
    gasto_janela_micros: dict[str, int],
    gasto_hoje_micros: dict[str, int],
    *,
    today: date,
) -> list[dict[str, Any]]:
    """O ritmo de cada orcamento COMPARTILHADO das campanhas listadas.

    O gasto vem do proprio orcamento (`gasto_janela_micros`, `gasto_hoje_micros`), nao da
    soma das linhas: inclui campanha pausada no mes ou cortada pelo `limit`. Orcamento
    que a query rodou e nao trouxe e gasto zero medido, como o gasto de hoje (F199). No
    dia 1 a janela e hoje, e o gasto de hoje e o da janela.
    """
    _, dias_fechados, _ = _calendario(today)
    por_orcamento: dict[str, dict[str, Any]] = {}
    for r in rows:
        if not r["orcamento_compartilhado"]:
            continue
        orc = por_orcamento.setdefault(
            r["budget_id"],
            {
                "budget_id": r["budget_id"],
                "budget_name": r["budget_name"],
                "daily_budget_brl": r["daily_budget_brl"],
                "campaign_ids": [],
            },
        )
        if r["campaign_id"] not in orc["campaign_ids"]:
            orc["campaign_ids"].append(r["campaign_id"])

    out: list[dict[str, Any]] = []
    for orc in por_orcamento.values():
        janela_micros = gasto_janela_micros.get(orc["budget_id"], 0)
        hoje_micros = (
            janela_micros if dias_fechados == 0 else gasto_hoje_micros.get(orc["budget_id"], 0)
        )
        mtd = micros_to_currency(janela_micros)
        ritmo = _ritmo(mtd, orc["daily_budget_brl"], today=today)
        out.append(
            {
                **orc,
                "monthly_budget_brl": ritmo["monthly_budget_brl"],
                "spent_mtd_brl": mtd,
                "gasto_hoje_brl": micros_to_currency(hoje_micros),
                "projected_monthly_brl": ritmo["projected_monthly_brl"],
                "spent_pct_of_monthly_budget": ritmo["spent_pct_of_monthly_budget"],
                "projection_vs_budget_pct": ritmo["projection_vs_budget_pct"],
            }
        )
    return sorted(out, key=lambda x: -x["spent_mtd_brl"])


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
    truncated = len(rows) > limit
    rows = rows[:limit]
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
        "campaigns": _project(rows, gasto_hoje, today=today),
        "orcamentos_compartilhados": _projeta_orcamentos(rows, orc_janela, orc_hoje, today=today),
    }
