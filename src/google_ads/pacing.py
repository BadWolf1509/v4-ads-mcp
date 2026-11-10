"""Pacing Google: projecao do mes por campanha e por orcamento compartilhado. Calculo puro, sem I/O."""

from datetime import date
from typing import Any

from src.google_ads.queries._common import micros_to_currency
from src.janelas import calendario_do_mes
from src.razoes import arredondado, percentual, razao


def ritmo(mtd: float, daily_budget: float, *, today: date) -> dict[str, Any]:
    """Projecao pelos dias fechados e os dois percentuais contra o orcamento do mes."""
    days_in_month, dias_fechados, _ = calendario_do_mes(today)
    daily_avg = razao(mtd, dias_fechados)
    projected = arredondado(None if daily_avg is None else daily_avg * days_in_month, 2)
    budget_monthly = round(daily_budget * days_in_month, 2)
    return {
        "monthly_budget_brl": budget_monthly,
        "projected_monthly_brl": projected,
        "spent_pct_of_monthly_budget": arredondado(percentual(razao(mtd, budget_monthly)), 1),
        "projection_vs_budget_pct": arredondado(percentual(razao(projected, budget_monthly)), 1),
    }


def projetar_linhas(
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
    `orcamentos_compartilhados` (`projetar_orcamentos`).
    """
    _, dias_fechados, days_remaining = calendario_do_mes(today)

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
        rt = ritmo(mtd, c["daily_budget_brl"], today=today)
        if c["orcamento_compartilhado"]:
            rt["spent_pct_of_monthly_budget"] = None
            rt["projection_vs_budget_pct"] = None
        out.append(
            {
                "campaign_id": c["campaign_id"],
                "campaign_name": c["campaign_name"],
                "daily_budget_brl": c["daily_budget_brl"],
                "budget_id": c["budget_id"],
                "orcamento_compartilhado": c["orcamento_compartilhado"],
                "spent_mtd_brl": mtd,
                "gasto_hoje_brl": micros_to_currency(hoje_micros),
                "spent_pct_of_monthly_budget": rt["spent_pct_of_monthly_budget"],
                "days_elapsed": dias_fechados,
                "days_remaining": days_remaining,
                "projected_monthly_brl": rt["projected_monthly_brl"],
                "projection_vs_budget_pct": rt["projection_vs_budget_pct"],
                "delivery_method": c["delivery_method"],
            }
        )
    return sorted(out, key=lambda x: -x["spent_mtd_brl"])


def projetar_orcamentos(
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
    _, dias_fechados, _ = calendario_do_mes(today)
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
        rt = ritmo(mtd, orc["daily_budget_brl"], today=today)
        out.append(
            {
                **orc,
                "monthly_budget_brl": rt["monthly_budget_brl"],
                "spent_mtd_brl": mtd,
                "gasto_hoje_brl": micros_to_currency(hoje_micros),
                "projected_monthly_brl": rt["projected_monthly_brl"],
                "spent_pct_of_monthly_budget": rt["spent_pct_of_monthly_budget"],
                "projection_vs_budget_pct": rt["projection_vs_budget_pct"],
            }
        )
    return sorted(out, key=lambda x: -x["spent_mtd_brl"])
