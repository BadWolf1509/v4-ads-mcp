"""GAQL queries for client-report tools."""

from datetime import date

from src.google_ads.queries._common import gaql_date_clause

# C5: o corte (`LIMIT top_n`) acontece NO GOOGLE, entao o `ORDER BY` tem que ser
# a metrica que o gestor pediu. Um mapa so, compartilhado pelos dois builders:
# copia em cada funcao e como as duas divergem sem ninguem notar.
_ORDER_FIELD = {
    "cost": "metrics.cost_micros",
    "conversions": "metrics.conversions",
    "clicks": "metrics.clicks",
    "impressions": "metrics.impressions",
}


# Desempate. Sem ele, "top 10 por conversoes" numa conta de cauda longa e quase
# todo empate em ZERO, e o Google nao garante ordem estavel entre linhas de mesmo
# valor: duas chamadas iguais devolvem keywords diferentes (F98/F88 — `LIMIT` sem
# `ORDER BY` que ordene de verdade). Custo desc como criterio secundario nao e
# arbitrario: entre linhas empatadas na metrica pedida, a mais cara e a que o
# gestor precisa ver. Sondado em 07/09 (`validate_gaql`): `ORDER BY a DESC, b
# DESC` e aceito, e `metrics.cost_micros` ja esta no SELECT das duas queries.
_DESEMPATE = "metrics.cost_micros"


def _order_by(metric: str) -> str:
    """Clausula `ORDER BY` (sem a palavra) para `metric`, com desempate.

    O `enum` do schema da tool valida a montante, mas o builder nao depende
    disso (F87): metrica desconhecida estoura aqui, em vez de virar um
    `ORDER BY` silenciosamente errado — que e o proprio defeito C5 por outra
    porta. Os quatro campos ja estao no SELECT das duas queries, e precisam
    continuar: sondado em 07/09 via `validate_gaql`, o Google recusa
    `ORDER BY` de campo fora do SELECT.
    """
    try:
        campo = _ORDER_FIELD[metric]
    except KeyError:
        raise KeyError(
            f"metrica {metric!r} nao e ordenavel; use uma de {sorted(_ORDER_FIELD)}"
        ) from None
    if campo == _DESEMPATE:
        return f"{campo} DESC"
    return f"{campo} DESC, {_DESEMPATE} DESC"


def funnel_query(start: date, end: date) -> str:
    """Aggregate funnel metrics from customer-level for the period."""
    return f"""
        SELECT
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value
        FROM customer
        WHERE {gaql_date_clause(start, end)}
    """.strip()


def top_keywords_query(start: date, end: date, top_n: int, *, metric: str) -> str:
    """Top N keywords by `metric`: o Google ordena e corta, nesta ordem.

    `metric` entra no `ORDER BY` porque o `LIMIT` e do lado do Google — se a
    ordenacao nao for a pedida, o top-N devolvido e o top-N de OUTRA coluna, e
    nenhum re-sort no cliente traz de volta a linha que nao veio (C5).
    """
    return f"""
        SELECT
          ad_group_criterion.criterion_id,
          ad_group_criterion.keyword.text,
          ad_group_criterion.keyword.match_type,
          ad_group.id, ad_group.name,
          campaign.id, campaign.name,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM keyword_view
        WHERE {gaql_date_clause(start, end)}
          AND ad_group_criterion.status = 'ENABLED'
        ORDER BY {_order_by(metric)}
        LIMIT {top_n}
    """.strip()


def top_creatives_query(start: date, end: date, top_n: int, *, metric: str) -> str:
    """Top N RSAs by `metric`: o Google ordena e corta, nesta ordem (ver C5)."""
    return f"""
        SELECT
          ad_group_ad.ad.id,
          ad_group_ad.ad.responsive_search_ad.headlines,
          ad_group_ad.ad.responsive_search_ad.descriptions,
          ad_group_ad.ad_strength,
          ad_group.id, ad_group.name,
          campaign.id, campaign.name,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM ad_group_ad
        WHERE {gaql_date_clause(start, end)}
          AND ad_group_ad.status = 'ENABLED'
        ORDER BY {_order_by(metric)}
        LIMIT {top_n}
    """.strip()
