"""Asserções de TEXTO GAQL nos query builders (overview / client_report / recommendations /
performance / tactical).

Os tools que consomem estes builders patcham `run_report` nos testes, então um typo
na string GAQL (campo errado, FROM errado, WHERE/ORDER BY quebrado) passa despercebido.
Estes testes chamam os builders diretos e asseveram os fragmentos GAQL esperados —
SELECT dos campos certos, FROM do recurso certo, cláusulas WHERE/ORDER BY/LIMIT chave.

Modelo: tests/unit/test_performance_breakdown.py (asserção de `FROM customer`,
`segments.device`, etc.). performance.py/tactical.py alimentam os 8 reports antigos
(get_campaign_performance, get_keyword_performance, etc.) que seguem em uso ativo
até a Fase 2B (soak) — typo aqui é prod quebrada.
"""

import re
from datetime import date

import pytest

from src.google_ads.queries.change_history import change_history_query
from src.google_ads.queries.client_report import (
    funnel_query,
    top_creatives_query,
    top_keywords_query,
)
from src.google_ads.queries.overview import budget_pacing_query, overview_query
from src.google_ads.queries.performance import (
    ad_group_performance_query,
    campaign_performance_query,
    device_performance_query,
    geo_performance_query,
    hourly_performance_query,
)
from src.google_ads.queries.recommendations import recommendations_query
from src.google_ads.queries.tactical import (
    ad_performance_query,
    audience_performance_query,
    conversion_actions_query,
    keyword_performance_query,
    negative_keywords_audit_query,
    search_terms_query,
)

_S, _E = date(2026, 1, 1), date(2026, 1, 31)

# Cláusula de data que gaql_date_clause emite pro range acima (formato ISO, aspas simples).
_DATE_CLAUSE = "segments.date BETWEEN '2026-01-01' AND '2026-01-31'"


# ---------------------------------------------------------------------------
# overview.py
# ---------------------------------------------------------------------------


def test_overview_query_selects_customer_metrics() -> None:
    q = overview_query(_S, _E)
    assert "FROM customer" in q
    for field in (
        "metrics.impressions",
        "metrics.clicks",
        "metrics.cost_micros",
        "metrics.conversions",
        "metrics.conversions_value",
        "metrics.ctr",
        "metrics.average_cpc",
        "metrics.cost_per_conversion",
    ):
        assert field in q, f"faltou {field} no SELECT do overview_query"


def test_overview_query_where_date_clause() -> None:
    q = overview_query(_S, _E)
    assert _DATE_CLAUSE in q


def test_budget_pacing_query_shape() -> None:
    q = budget_pacing_query()
    assert "FROM campaign" in q
    for field in (
        "campaign.id",
        "campaign.name",
        "campaign.status",
        "campaign_budget.amount_micros",
        "campaign_budget.delivery_method",
        "metrics.cost_micros",
    ):
        assert field in q, f"faltou {field} no SELECT do budget_pacing_query"
    # Só campanhas ativas, gasto do mês corrente.
    assert "campaign.status = 'ENABLED'" in q
    assert "segments.date DURING THIS_MONTH" in q


# ---------------------------------------------------------------------------
# client_report.py
# ---------------------------------------------------------------------------


def test_funnel_query_shape() -> None:
    q = funnel_query(_S, _E)
    assert "FROM customer" in q
    for field in (
        "metrics.impressions",
        "metrics.clicks",
        "metrics.cost_micros",
        "metrics.conversions",
        "metrics.conversions_value",
    ):
        assert field in q, f"faltou {field} no SELECT do funnel_query"
    assert _DATE_CLAUSE in q


# C5: o `ORDER BY` e a metrica que o gestor pediu, porque o corte (`LIMIT top_n`)
# acontece NO GOOGLE. Ordenar por custo e reordenar depois no cliente devolve o
# top-N por custo reordenado — a keyword barata que converte muito nunca chega.
_ORDEM = {
    "cost": "metrics.cost_micros",
    "conversions": "metrics.conversions",
    "clicks": "metrics.clicks",
    "impressions": "metrics.impressions",
}


def test_top_keywords_query_shape_and_order() -> None:
    q = top_keywords_query(_S, _E, 5, metric="cost")
    assert "FROM keyword_view" in q
    for field in (
        "ad_group_criterion.criterion_id",
        "ad_group_criterion.keyword.text",
        "ad_group_criterion.keyword.match_type",
        "ad_group.id",
        "campaign.id",
        "metrics.cost_micros",
    ):
        assert field in q, f"faltou {field} no SELECT do top_keywords_query"
    assert _DATE_CLAUSE in q
    assert "ad_group_criterion.status = 'ENABLED'" in q
    assert "ORDER BY metrics.cost_micros DESC" in q
    assert "LIMIT 5" in q


def test_top_keywords_query_limit_is_parameterized() -> None:
    assert "LIMIT 25" in top_keywords_query(_S, _E, 25, metric="cost")
    assert "LIMIT 5" not in top_keywords_query(_S, _E, 25, metric="cost")


def test_top_creatives_query_shape_and_order() -> None:
    q = top_creatives_query(_S, _E, 3, metric="cost")
    assert "FROM ad_group_ad" in q
    for field in (
        "ad_group_ad.ad.id",
        "ad_group_ad.ad.responsive_search_ad.headlines",
        "ad_group_ad.ad.responsive_search_ad.descriptions",
        "ad_group_ad.ad_strength",
        "campaign.name",
        "metrics.cost_micros",
    ):
        assert field in q, f"faltou {field} no SELECT do top_creatives_query"
    assert _DATE_CLAUSE in q
    assert "ad_group_ad.status = 'ENABLED'" in q
    assert "ORDER BY metrics.cost_micros DESC" in q
    assert "LIMIT 3" in q


def test_top_keywords_ordena_pela_metrica_pedida() -> None:
    for metric, campo in _ORDEM.items():
        q = top_keywords_query(_S, _E, 10, metric=metric)
        assert f"ORDER BY {campo} DESC" in q, metric


def test_top_creatives_ordena_pela_metrica_pedida() -> None:
    for metric, campo in _ORDEM.items():
        q = top_creatives_query(_S, _E, 10, metric=metric)
        assert f"ORDER BY {campo} DESC" in q, metric


def test_o_campo_do_order_by_esta_no_select() -> None:
    """Sondado em 07/09 via `validate_gaql`: o Google recusa `ORDER BY` de campo
    fora do SELECT — "The following field must be present in SELECT clause:
    'metrics.conversions'". As duas queries ja selecionam as quatro metricas,
    entao o fix do C5 nao mexeu no SELECT; esta assercao e o que impede alguem
    de "enxugar" o SELECT depois e quebrar o `ORDER BY` em producao.

    Casa por token (`(?![\\w.])`) e nao por substring porque
    `metrics.conversions_value` CONTEM `metrics.conversions`: um `in` cru
    passaria verde num SELECT que tivesse perdido a metrica de conversao e
    guardado so a de valor.
    """
    for metric, campo in _ORDEM.items():
        for nome, q in (
            ("top_keywords_query", top_keywords_query(_S, _E, 10, metric=metric)),
            ("top_creatives_query", top_creatives_query(_S, _E, 10, metric=metric)),
        ):
            select = q.split("FROM")[0]
            assert re.search(rf"{re.escape(campo)}(?![\w.])", select), (
                f"{nome}/{metric}: {campo} fora do SELECT — o Google recusa a query"
            )


def test_metrica_desconhecida_e_recusada_no_builder() -> None:
    """O `enum` do schema valida a montante, mas o builder NAO depende dele
    (F87: nao assumir a superficie de quem chama). Metrica fora do mapa tem
    que estourar aqui, e nao virar `ORDER BY` silenciosamente errado.
    """
    for builder in (top_keywords_query, top_creatives_query):
        with pytest.raises(KeyError):
            builder(_S, _E, 10, metric="conversions_value")


# ---------------------------------------------------------------------------
# recommendations.py
# ---------------------------------------------------------------------------


def test_recommendations_query_shape() -> None:
    q = recommendations_query()
    assert "FROM recommendation" in q
    for field in (
        "recommendation.resource_name",
        "recommendation.type",
        "recommendation.dismissed",
    ):
        assert field in q, f"faltou {field} no SELECT do recommendations_query"
    # Só pendentes (não dispensadas).
    assert "recommendation.dismissed = false" in q
    # Métricas de impacto foram intencionalmente omitidas (docstring) — guard.
    assert "base_metrics" not in q
    assert "potential_metrics" not in q


# ---------------------------------------------------------------------------
# performance.py
# ---------------------------------------------------------------------------


def test_campaign_performance_query_shape_status_filter_and_order() -> None:
    q = campaign_performance_query(_S, _E, "enabled", 10)
    assert "FROM campaign" in q
    for field in (
        "campaign.id",
        "campaign.name",
        "campaign.status",
        "campaign.advertising_channel_type",
        "metrics.impressions",
        "metrics.clicks",
        "metrics.cost_micros",
        "metrics.conversions",
        "metrics.conversions_value",
    ):
        assert field in q, f"faltou {field} no SELECT do campaign_performance_query"
    assert _DATE_CLAUSE in q
    assert "campaign.status = 'ENABLED'" in q
    assert "ORDER BY metrics.cost_micros DESC" in q
    assert "LIMIT 11" in q  # +1: a linha sentinela


def test_campaign_performance_query_status_all_omits_status_clause() -> None:
    q = campaign_performance_query(_S, _E, "all", 10)
    assert "campaign.status = " not in q


def test_ad_group_performance_query_shape_status_filter_and_order() -> None:
    q = ad_group_performance_query(_S, _E, "paused", 20)
    assert "FROM ad_group" in q
    for field in (
        "ad_group.id",
        "ad_group.name",
        "ad_group.status",
        "campaign.id",
        "campaign.name",
        "metrics.impressions",
        "metrics.clicks",
        "metrics.cost_micros",
        "metrics.conversions",
        "metrics.conversions_value",
    ):
        assert field in q, f"faltou {field} no SELECT do ad_group_performance_query"
    assert _DATE_CLAUSE in q
    assert "ad_group.status = 'PAUSED'" in q
    assert "ORDER BY metrics.cost_micros DESC" in q
    assert "LIMIT 21" in q  # +1: a linha sentinela


def test_ad_group_performance_query_status_all_omits_status_clause() -> None:
    q = ad_group_performance_query(_S, _E, "all", 20)
    assert "ad_group.status = " not in q


def test_device_performance_query_shape() -> None:
    q = device_performance_query(_S, _E)
    assert "FROM customer" in q
    for field in (
        "segments.device",
        "metrics.impressions",
        "metrics.clicks",
        "metrics.cost_micros",
        "metrics.conversions",
        "metrics.conversions_value",
    ):
        assert field in q, f"faltou {field} no SELECT do device_performance_query"
    assert _DATE_CLAUSE in q


def test_geo_performance_query_shape_and_order() -> None:
    q = geo_performance_query(_S, _E, 15)
    assert "FROM geographic_view" in q
    for field in (
        "geographic_view.country_criterion_id",
        "metrics.impressions",
        "metrics.clicks",
        "metrics.cost_micros",
        "metrics.conversions",
        "metrics.conversions_value",
    ):
        assert field in q, f"faltou {field} no SELECT do geo_performance_query"
    assert _DATE_CLAUSE in q
    assert "ORDER BY metrics.cost_micros DESC" in q
    assert "LIMIT 16" in q  # +1: a linha sentinela


def test_hourly_performance_query_shape() -> None:
    q = hourly_performance_query(_S, _E)
    assert "FROM customer" in q
    for field in (
        "segments.hour",
        "segments.day_of_week",
        "metrics.impressions",
        "metrics.clicks",
        "metrics.cost_micros",
        "metrics.conversions",
        "metrics.conversions_value",
    ):
        assert field in q, f"faltou {field} no SELECT do hourly_performance_query"
    assert _DATE_CLAUSE in q


# ---------------------------------------------------------------------------
# tactical.py
# ---------------------------------------------------------------------------


def test_keyword_performance_query_shape_status_filter_and_order() -> None:
    q = keyword_performance_query(_S, _E, "enabled", 25)
    assert "FROM keyword_view" in q
    for field in (
        "ad_group_criterion.criterion_id",
        "ad_group_criterion.keyword.text",
        "ad_group_criterion.keyword.match_type",
        "ad_group_criterion.status",
        "ad_group_criterion.negative",
        "ad_group_criterion.quality_info.quality_score",
        "ad_group_criterion.quality_info.creative_quality_score",
        "ad_group_criterion.quality_info.post_click_quality_score",
        "ad_group_criterion.quality_info.search_predicted_ctr",
        "ad_group_criterion.position_estimates.first_page_cpc_micros",
        "ad_group_criterion.position_estimates.top_of_page_cpc_micros",
        "ad_group.id",
        "ad_group.name",
        "campaign.id",
        "campaign.name",
        "metrics.impressions",
        "metrics.clicks",
        "metrics.cost_micros",
        "metrics.conversions",
        "metrics.conversions_value",
    ):
        assert field in q, f"faltou {field} no SELECT do keyword_performance_query"
    assert _DATE_CLAUSE in q
    assert "ad_group_criterion.status = 'ENABLED'" in q
    assert "ORDER BY metrics.cost_micros DESC" in q
    assert "LIMIT 26" in q  # +1: a linha sentinela


def test_keyword_performance_query_status_all_omits_status_clause() -> None:
    q = keyword_performance_query(_S, _E, "all", 25)
    assert "ad_group_criterion.status = " not in q


def test_keyword_performance_query_metric_filters_appended() -> None:
    q = keyword_performance_query(
        _S, _E, "enabled", 25, min_cost_brl=10.0, min_clicks=5, min_conversions=1.0
    )
    assert "AND metrics.cost_micros >= 10000000" in q
    assert "AND metrics.clicks >= 5" in q
    assert "AND metrics.conversions > 1.0" in q


def test_search_terms_query_shape_and_order() -> None:
    q = search_terms_query(_S, _E, 30)
    assert "FROM search_term_view" in q
    for field in (
        "search_term_view.search_term",
        "search_term_view.status",
        "ad_group.id",
        "ad_group.name",
        "campaign.id",
        "campaign.name",
        "metrics.impressions",
        "metrics.clicks",
        "metrics.cost_micros",
        "metrics.conversions",
        "metrics.conversions_value",
    ):
        assert field in q, f"faltou {field} no SELECT do search_terms_query"
    assert _DATE_CLAUSE in q
    assert "ORDER BY metrics.cost_micros DESC" in q
    assert "LIMIT 31" in q  # +1: a linha sentinela


def test_search_terms_query_metric_filters_appended() -> None:
    q = search_terms_query(_S, _E, 30, min_cost_brl=5.5, min_clicks=2)
    assert "AND metrics.cost_micros >= 5500000" in q
    assert "AND metrics.clicks >= 2" in q
    # min_conversions não informado -> cláusula de conversions ausente.
    assert "metrics.conversions >" not in q


def test_negative_keywords_audit_query_shape() -> None:
    q = negative_keywords_audit_query()
    assert "FROM campaign_criterion" in q
    for field in (
        "campaign_criterion.criterion_id",
        "campaign_criterion.negative",
        "campaign_criterion.keyword.text",
        "campaign_criterion.keyword.match_type",
        "campaign.id",
        "campaign.name",
    ):
        assert field in q, f"faltou {field} no SELECT do negative_keywords_audit_query"
    # Só negativas de tipo KEYWORD (não outros tipos de criterion negativo).
    assert "campaign_criterion.negative = true" in q
    assert "campaign_criterion.type = 'KEYWORD'" in q
    # Sem filtro de data — negativas não são segmentadas por período.
    assert "segments.date" not in q


def test_ad_performance_query_shape_status_filter_and_order() -> None:
    q = ad_performance_query(_S, _E, "enabled", 12)
    assert "FROM ad_group_ad" in q
    for field in (
        "ad_group_ad.ad.id",
        "ad_group_ad.status",
        "ad_group_ad.ad.type",
        "ad_group_ad.ad.responsive_search_ad.headlines",
        "ad_group_ad.ad.responsive_search_ad.descriptions",
        "ad_group_ad.ad.final_urls",
        "ad_group_ad.ad_strength",
        "ad_group.id",
        "ad_group.name",
        "campaign.id",
        "campaign.name",
        "metrics.impressions",
        "metrics.clicks",
        "metrics.cost_micros",
        "metrics.conversions",
        "metrics.conversions_value",
    ):
        assert field in q, f"faltou {field} no SELECT do ad_performance_query"
    assert _DATE_CLAUSE in q
    assert "ad_group_ad.status = 'ENABLED'" in q
    assert "ORDER BY metrics.cost_micros DESC" in q
    assert "LIMIT 13" in q  # +1: a linha sentinela


def test_ad_performance_query_status_all_omits_status_clause() -> None:
    q = ad_performance_query(_S, _E, "all", 12)
    assert "ad_group_ad.status = " not in q


def test_audience_performance_query_shape_and_order() -> None:
    q = audience_performance_query(_S, _E, 8)
    assert "FROM ad_group_audience_view" in q
    for field in (
        "ad_group_audience_view.resource_name",
        "ad_group_criterion.criterion_id",
        "ad_group_criterion.user_list.user_list",
        "ad_group_criterion.user_interest.user_interest_category",
        "ad_group.id",
        "ad_group.name",
        "campaign.id",
        "campaign.name",
        "metrics.impressions",
        "metrics.clicks",
        "metrics.cost_micros",
        "metrics.conversions",
        "metrics.conversions_value",
    ):
        assert field in q, f"faltou {field} no SELECT do audience_performance_query"
    assert _DATE_CLAUSE in q
    assert "ORDER BY metrics.cost_micros DESC" in q
    assert "LIMIT 9" in q  # +1: a linha sentinela


def test_conversion_actions_query_shape() -> None:
    q = conversion_actions_query()
    assert "FROM conversion_action" in q
    for field in (
        "conversion_action.id",
        "conversion_action.name",
        "conversion_action.status",
        "conversion_action.category",
        "conversion_action.type",
        "conversion_action.counting_type",
        "conversion_action.attribution_model_settings.attribution_model",
        "conversion_action.value_settings.default_value",
        "conversion_action.value_settings.always_use_default_value",
        "conversion_action.primary_for_goal",
        "conversion_action.include_in_conversions_metric",
    ):
        assert field in q, f"faltou {field} no SELECT do conversion_actions_query"
    # Sem filtro de data/status — lista todas as conversion actions da conta.
    assert "WHERE" not in q


# ---------------------------------------------------------------------------
# A linha sentinela (PR 4, §3.2)
#
# Todo builder aqui serve uma tool que declara `limit` no schema e devolve
# `truncated`. `aplicar_limite` decide o corte comparando `len(linhas) >
# limite` — comparacao que so distingue "vieram exatamente `limite`" de
# "havia mais" se a consulta pediu `limite + 1`. Com `LIMIT {limit}` o
# `truncated` responde `false` para sempre, e o gestor le "nao cortei" de uma
# resposta cortada.
#
# O par de assercoes e deliberado: a primeira prende o `+1`, a segunda prende
# que o teto exato NAO ficou (um builder que emitisse as duas clausulas, ou
# que somasse em outro lugar, passaria so com a primeira).
# ---------------------------------------------------------------------------


def test_campaign_performance_query_pede_uma_linha_a_mais() -> None:
    q = campaign_performance_query(_S, _E, "ENABLED", 100)
    assert "LIMIT 101" in q
    assert "LIMIT 100" not in q


def test_ad_group_performance_query_pede_uma_linha_a_mais() -> None:
    q = ad_group_performance_query(_S, _E, "ENABLED", 100)
    assert "LIMIT 101" in q
    assert "LIMIT 100" not in q


def test_geo_performance_query_pede_uma_linha_a_mais() -> None:
    q = geo_performance_query(_S, _E, 100)
    assert "LIMIT 101" in q
    assert "LIMIT 100" not in q


def test_keyword_performance_query_pede_uma_linha_a_mais() -> None:
    q = keyword_performance_query(_S, _E, "ENABLED", 100)
    assert "LIMIT 101" in q
    assert "LIMIT 100" not in q


def test_search_terms_query_pede_uma_linha_a_mais() -> None:
    q = search_terms_query(_S, _E, 100)
    assert "LIMIT 101" in q
    assert "LIMIT 100" not in q


def test_ad_performance_query_pede_uma_linha_a_mais() -> None:
    q = ad_performance_query(_S, _E, "ENABLED", 100)
    assert "LIMIT 101" in q
    assert "LIMIT 100" not in q


def test_audience_performance_query_pede_uma_linha_a_mais() -> None:
    q = audience_performance_query(_S, _E, 100)
    assert "LIMIT 101" in q
    assert "LIMIT 100" not in q


def test_change_history_query_pede_uma_linha_a_mais() -> None:
    """Janela propria de 7 dias: `_S.._E` sao 31 dias e o builder recusa
    acima de 30 (`RangeTooWideError`)."""
    q = change_history_query(
        start=date(2026, 1, 1),
        end=date(2026, 1, 7),
        resource_types=None,
        operation_types=None,
        user_emails=None,
        client_types=None,
        limit=100,
    )
    assert "LIMIT 101" in q
    assert "LIMIT 100" not in q


def test_o_top_n_tem_desempate_estavel() -> None:
    """`LIMIT` sobre `ORDER BY` que empata nao ordena — escolhe ao acaso.

    "Top 10 por conversoes" numa conta de cauda longa e quase todo empate em
    ZERO, e o Google nao garante ordem estavel entre linhas de mesmo valor:
    duas chamadas iguais devolvem keywords diferentes, e o gestor nao tem como
    saber que a lista mudou por acaso (F98/F88).

    Custo desc como criterio secundario: entre empatadas na metrica pedida, a
    mais cara e a que precisa ser vista. A mudanca de producao que deixa este
    teste vermelho e apagar o segundo campo do `ORDER BY`.
    """
    for metric in ("conversions", "clicks", "impressions"):
        for q in (
            top_keywords_query(_S, _E, 10, metric=metric),
            top_creatives_query(_S, _E, 10, metric=metric),
        ):
            assert "DESC, metrics.cost_micros DESC" in q, f"{metric}: sem desempate"


def test_ordenar_por_custo_nao_repete_o_campo_no_desempate() -> None:
    """`ORDER BY metrics.cost_micros DESC, metrics.cost_micros DESC` seria
    aceito pelo Google e diria a mesma coisa duas vezes — ruido que faz o
    proximo leitor procurar um significado que nao existe."""
    for q in (
        top_keywords_query(_S, _E, 10, metric="cost"),
        top_creatives_query(_S, _E, 10, metric="cost"),
    ):
        assert q.count("metrics.cost_micros DESC") == 1


def test_a_grade_vem_agrupada_por_campanha_e_a_regra_da_borda_depende_disso() -> None:
    """`campanhas_com_grade_incerta` marca como desconhecida a campanha da
    ULTIMA linha lida — e isso so e correto porque as linhas chegam agrupadas
    por campanha.

    Sem `ORDER BY campaign.id`, as janelas de varias campanhas viriam
    intercaladas e o corte cairia no meio de VARIAS ao mesmo tempo; a regra
    marcaria uma e deixaria as outras reportando grade parcial como se fosse
    completa — exatamente o defeito (F147) que a regra existe para fechar, de
    volta em silencio.

    O acoplamento existia e nao estava preso por nada. Esta assercao e o unico
    lugar onde ele fica escrito: a mudanca de producao que a derruba e trocar a
    ordenacao do builder, que hoje ninguem associaria ao resumo da outra ponta.
    """
    from src.google_ads.queries.ad_schedule import ad_schedule_query

    q = ad_schedule_query(campaign_ids=None, status="enabled", limit=10)
    ordem = q[q.index("ORDER BY") :]
    assert ordem.split("ORDER BY")[1].strip().startswith("campaign.id"), (
        "a grade deixou de vir agrupada por campanha; a regra da borda em "
        "`campanhas_com_grade_incerta` depende disso e passa a marcar a "
        f"campanha errada. ORDER BY atual: {ordem!r}"
    )
