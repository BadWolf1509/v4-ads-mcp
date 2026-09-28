"""GAQL queries for visao geral tools (account_overview, budget_pacing)."""

from datetime import date
from typing import Any

from src.google_ads.queries._common import gaql_date_clause, janela_aplicada


def overview_query(date_start: date, date_end: date) -> tuple[str, dict[str, Any]]:
    """Metricas agregadas da conta (recurso `customer`) no periodo.

    Nao filtra status: a docstring antiga dizia "across all enabled campaigns",
    e a query nunca teve esse corte.
    """
    gaql = f"""
        SELECT
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value,
          metrics.ctr,
          metrics.average_cpc,
          metrics.cost_per_conversion
        FROM customer
        WHERE {gaql_date_clause(date_start, date_end)}
    """.strip()
    return gaql, {"date_range": janela_aplicada(date_start, date_end)}


def budget_pacing_query(
    date_start: date, date_end: date, limit: int = 100
) -> tuple[str, dict[str, Any]]:
    """Orcamento atual + gasto no mes, por campanha ativa.

    F98 — `limit + 1` (a linha extra revela o corte) **e** `ORDER BY` explícito:
    o tool ordena por gasto DESC no fim, então cortar um conjunto não-ordenado
    entregaria N campanhas arbitrárias reordenadas entre si, parecendo o topo de
    gasto da conta sem ser — a classe F88 ("truncar e depois ordenar").

    F199: a janela e a do `THIS_MONTH` de `janelas.py` — os dias FECHADOS do mes, ate
    ontem; no dia 1, so hoje. Era `DURING THIS_MONTH`, que inclui o dia corrente, e a
    projecao dividia esse gasto parcial por um dia inteiro.
    """
    gaql = f"""
        SELECT
          campaign.id,
          campaign.name,
          campaign.status,
          campaign_budget.amount_micros,
          campaign_budget.delivery_method,
          metrics.cost_micros
        FROM campaign
        WHERE campaign.status = 'ENABLED'
          AND {gaql_date_clause(date_start, date_end)}
        ORDER BY metrics.cost_micros DESC
        LIMIT {limit + 1}
    """.strip()
    filtros: dict[str, Any] = {
        "campaign_status": "ENABLED",
        "date_range": janela_aplicada(date_start, date_end),
    }
    return gaql, filtros


def budget_pacing_hoje_query(today: date, campaign_ids: list[str]) -> tuple[str, dict[str, Any]]:
    """Gasto de HOJE — dia ainda aberto — das campanhas que a projecao listou (F199).

    Fica fora da projecao, que so usa dias fechados; serve de sinal de estouro no dia.
    `LIMIT 1000` e teto estrutural, nao corte: uma linha por campanha, e a lista vem
    do `limit` da tool, que o schema limita a 1000.
    """
    if not 1 <= len(campaign_ids) <= 1000:
        raise ValueError(f"budget_pacing_hoje_query: 1 a 1000 campanhas, veio {len(campaign_ids)}")
    ids = ", ".join(str(int(x)) for x in campaign_ids)
    gaql = f"""
        SELECT
          campaign.id,
          metrics.cost_micros
        FROM campaign
        WHERE campaign.id IN ({ids})
          AND {gaql_date_clause(today, today)}
        LIMIT 1000
    """.strip()
    filtros: dict[str, Any] = {
        "campaign_ids": list(campaign_ids),
        "date_range": janela_aplicada(today, today),
    }
    return gaql, filtros
