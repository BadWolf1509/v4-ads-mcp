"""GAQL queries for performance analysis tools.

Cada funcao devolve `(gaql, filtros)`: `filtros` e o recorte que a query aplica,
montado junto da clausula do WHERE que o aplica. As tools o ecoam em
`filters_applied` (spec 2026-09-25, padrao do F191).
"""

from datetime import date
from typing import Any

from src.google_ads.queries._common import gaql_date_clause, janela_aplicada


def campaign_performance_query(
    start: date, end: date, status: str, limit: int
) -> tuple[str, dict[str, Any]]:
    filtros: dict[str, Any] = {"date_range": janela_aplicada(start, end)}
    status_clause = ""
    if status != "all":
        status_clause = f"AND campaign.status = '{status.upper()}'"
        filtros["campaign_status"] = status.upper()
    gaql = f"""
        SELECT
          campaign.id, campaign.name, campaign.status,
          campaign.advertising_channel_type,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value,
          metrics.search_impression_share,
          metrics.search_budget_lost_impression_share,
          metrics.search_rank_lost_impression_share,
          metrics.search_top_impression_share,
          metrics.search_absolute_top_impression_share
        FROM campaign
        WHERE {gaql_date_clause(start, end)} {status_clause}
        ORDER BY metrics.cost_micros DESC
        LIMIT {limit + 1}
    """.strip()
    return gaql, filtros


def ad_group_performance_query(
    start: date, end: date, status: str, limit: int
) -> tuple[str, dict[str, Any]]:
    filtros: dict[str, Any] = {"date_range": janela_aplicada(start, end)}
    status_clause = ""
    if status != "all":
        status_clause = f"AND ad_group.status = '{status.upper()}'"
        filtros["ad_group_status"] = status.upper()
    gaql = f"""
        SELECT
          ad_group.id, ad_group.name, ad_group.status,
          campaign.id, campaign.name,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM ad_group
        WHERE {gaql_date_clause(start, end)} {status_clause}
        ORDER BY metrics.cost_micros DESC
        LIMIT {limit + 1}
    """.strip()
    return gaql, filtros


def device_performance_query(start: date, end: date) -> tuple[str, dict[str, Any]]:
    gaql = f"""
        SELECT
          segments.device,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM customer
        WHERE {gaql_date_clause(start, end)}
    """.strip()
    return gaql, {"date_range": janela_aplicada(start, end)}


def geo_performance_query(start: date, end: date, limit: int) -> tuple[str, dict[str, Any]]:
    """Geographic performance from geographic_view (country-level criterion)."""
    gaql = f"""
        SELECT
          geographic_view.country_criterion_id,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM geographic_view
        WHERE {gaql_date_clause(start, end)}
        ORDER BY metrics.cost_micros DESC
        LIMIT {limit + 1}
    """.strip()
    return gaql, {"date_range": janela_aplicada(start, end)}


def hourly_performance_query(start: date, end: date) -> tuple[str, dict[str, Any]]:
    gaql = f"""
        SELECT
          segments.hour, segments.day_of_week,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM customer
        WHERE {gaql_date_clause(start, end)}
    """.strip()
    return gaql, {"date_range": janela_aplicada(start, end)}


def conversion_action_breakdown_query(
    level: str, start: date, end: date, status: str, limit: int
) -> tuple[str, dict[str, Any]]:
    """Conversoes por acao de conversao, na conta ou por campanha (spec 2026-10-02 §3.1).

    So metricas de conversao: recortar por `segments.conversion_action` recusa custo
    (medido em 02/10) — nao existe CPA por acao. `ORDER BY` + `LIMIT limit+1` (F98: a
    linha a mais revela o corte). `conversions` segue o `include_in_conversions_metric`
    da acao; `all_conversions` soma todas.
    """
    filtros: dict[str, Any] = {"date_range": janela_aplicada(start, end)}
    if level == "account":
        recurso, campanha, status_clause = "customer", "", ""
    elif level == "campaign":
        recurso, campanha, status_clause = "campaign", "campaign.id, campaign.name,", ""
        if status != "all":
            status_clause = f"AND campaign.status = '{status.upper()}'"
            filtros["campaign_status"] = status.upper()
    else:
        raise ValueError(f"recorte por acao so em account ou campaign, veio {level!r}")
    gaql = f"""
        SELECT
          {campanha}
          segments.conversion_action,
          segments.conversion_action_name,
          segments.conversion_action_category,
          metrics.conversions, metrics.all_conversions,
          metrics.conversions_value, metrics.all_conversions_value
        FROM {recurso}
        WHERE {gaql_date_clause(start, end)} {status_clause}
        ORDER BY metrics.all_conversions DESC
        LIMIT {limit + 1}
    """.strip()
    return gaql, filtros


def conversion_action_flags_query(ids: list[str]) -> tuple[str, dict[str, Any]]:
    """As flags de cada acao do recorte: conta em `conversions`? e meta de lance?

    Acao que este recurso nao devolve (medido: "Conversation started", gerenciada pelo
    Google ou de outra conta) fica sem flag — quem chama marca `null` com motivo, nunca
    `false`. `int()` em cada id (F163); `LIMIT 1000` e teto estrutural, uma linha por id.
    """
    if not 1 <= len(ids) <= 1000:
        raise ValueError(f"conversion_action_flags_query: 1 a 1000 acoes, veio {len(ids)}")
    lista = ", ".join(str(int(x)) for x in ids)
    gaql = f"""
        SELECT
          conversion_action.id,
          conversion_action.include_in_conversions_metric,
          conversion_action.primary_for_goal,
          conversion_action.status,
          conversion_action.type
        FROM conversion_action
        WHERE conversion_action.id IN ({lista})
        LIMIT 1000
    """.strip()
    return gaql, {"conversion_action_ids": list(ids)}
