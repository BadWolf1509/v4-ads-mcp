"""F133: `audit_competitor_keywords` chamava gasto de `wasted` sem ler conversao.

A query selecionava `metrics.impressions, metrics.clicks, metrics.cost_micros` e
nada mais — a palavra `conversions` nao aparecia na tool. Mesmo assim o summary
publicava `total_cost_wasted_brl` e a tool emitia `suggested_negatives` por
brand, EXACT + PHRASE.

Caso real que originou o finding (conta 786-223-0676, 90 dias): termo de
concorrente com R$ 155,25 de custo e **9,00 conversoes** — CPA R$ 17,25, o
melhor da conta. A sugestao automatica mataria o ativo mais eficiente.

## Sinalizar, nao suprimir

`suggested_negatives` e emitido por **brand agregada**, nao por termo, entao
"nao sugerir o termo que converteu" nao tem onde encaixar. E suprimir a brand
que converteu faria a tool ficar muda exatamente quando o termo e valioso —
seria a 17a variante da silent-acceptance, trocando um defeito por outro da
mesma familia.

Razao decisiva, do gestor de campo: **a tool nao tem ERP.** Negativar exige
cross-check de catalogo, e o ERP derruba a maioria das propostas. Tool sem ERP
nunca deveria decidir, so instruir — e suprimir e decidir.

Entao a sugestao continua saindo, carregando o numero que a contradiz, em campo
ESTRUTURADO (nao so prosa no `reason`): sem isso as skills `v4-trafego` teriam
que parsear texto pra filtrar.

Gatilho e `conversions > 0`, e nao CPA relativo a media da conta: a "media" da
conta mistura brand com non-brand, praca com praca e match type com match type
— e mente com n pequeno (1 conversao a R$ 8 dispararia "otimo"). O flag e o
freio que manda abrir o ERP, nao o veredito.
"""

from __future__ import annotations

from src.google_ads.competitor_analysis import (
    SearchTermRow,
    match_competitor_brands,
)
from src.google_ads.queries.audit_competitor_keywords import (
    build_search_terms_query,
    dict_to_search_term_row,
)


def _st(
    *,
    search_term: str,
    cost_brl: float,
    conversions: float,
    conversions_value_brl: float = 0.0,
) -> SearchTermRow:
    return SearchTermRow(
        search_term=search_term,
        ad_group_name="AG1",
        campaign_name="C1",
        impressions=100,
        clicks=10,
        cost_brl=cost_brl,
        conversions=conversions,
        conversions_value_brl=conversions_value_brl,
    )


def test_query_de_search_terms_pede_conversao() -> None:
    """A metrica esta na MESMA tabela que a query ja visita — custo era uma linha."""
    q = build_search_terms_query(start_date="2026-06-01", end_date="2026-06-30")
    assert "metrics.conversions" in q
    assert "metrics.conversions_value" in q


def test_conversao_sobrevive_do_dict_ate_a_dataclass() -> None:
    """Fronteira parser -> dataclass: campo novo nao pode cair no caminho."""
    row = dict_to_search_term_row(
        {
            "search_term": "concorrente x",
            "ad_group_name": "AG1",
            "campaign_name": "C1",
            "impressions": 100,
            "clicks": 10,
            "cost_brl": 155.25,
            "conversions": 9.0,
            "conversions_value_brl": 1800.0,
        }
    )
    assert row.conversions == 9.0
    assert row.conversions_value_brl == 1800.0


def test_search_term_matched_carrega_conversao() -> None:
    """O gestor fecha CPA na linha: `cost_brl` ja existia, faltava a conversao."""
    _kw, matched_st, _sug, _tot, _cost = match_competitor_brands(
        keyword_rows=[],
        search_term_rows=[_st(search_term="concorrente x", cost_brl=155.25, conversions=9.0)],
        competitor_brands=["concorrente"],
        limit=100,
    )
    assert len(matched_st) == 1
    assert matched_st[0].conversions == 9.0


def test_brand_que_converteu_ainda_recebe_sugestao() -> None:
    """O anti-teste da supressao: ficar mudo aqui seria o defeito espelhado."""
    _kw, _st_out, suggested, _tot, _cost = match_competitor_brands(
        keyword_rows=[],
        search_term_rows=[_st(search_term="concorrente x", cost_brl=155.25, conversions=9.0)],
        competitor_brands=["concorrente"],
        limit=100,
    )
    assert {s.match_type for s in suggested} == {"EXACT", "PHRASE"}


def test_sugestao_carrega_conversao_em_campo_estruturado() -> None:
    """Sem isto, filtrar a sugestao perigosa exigiria parsear prosa."""
    _kw, _st_out, suggested, _tot, _cost = match_competitor_brands(
        keyword_rows=[],
        search_term_rows=[_st(search_term="concorrente x", cost_brl=155.25, conversions=9.0)],
        competitor_brands=["concorrente"],
        limit=100,
    )
    assert all(s.conversions == 9.0 for s in suggested)


def test_sugestao_de_brand_sem_conversao_fica_com_zero() -> None:
    """O gatilho e `> 0`: quem nao converteu segue sinalizado como seguro."""
    _kw, _st_out, suggested, _tot, _cost = match_competitor_brands(
        keyword_rows=[],
        search_term_rows=[_st(search_term="concorrente y", cost_brl=80.0, conversions=0.0)],
        competitor_brands=["concorrente"],
        limit=100,
    )
    assert all(s.conversions == 0.0 for s in suggested)


def test_conversao_agrega_por_brand_e_nao_por_termo() -> None:
    """A sugestao e por brand; a contra-evidencia tem que somar na mesma chave."""
    _kw, _st_out, suggested, _tot, _cost = match_competitor_brands(
        keyword_rows=[],
        search_term_rows=[
            _st(search_term="concorrente x", cost_brl=100.0, conversions=6.0),
            _st(search_term="concorrente y", cost_brl=55.25, conversions=3.0),
        ],
        competitor_brands=["concorrente"],
        limit=100,
    )
    assert all(s.conversions == 9.0 for s in suggested)


def test_reason_da_sugestao_mostra_o_cpa_quando_houve_conversao() -> None:
    """Quem le a prosa tem que ver o numero que desaconselha a acao."""
    _kw, _st_out, suggested, _tot, _cost = match_competitor_brands(
        keyword_rows=[],
        search_term_rows=[_st(search_term="concorrente x", cost_brl=155.25, conversions=9.0)],
        competitor_brands=["concorrente"],
        limit=100,
    )
    exact = next(s for s in suggested if s.match_type == "EXACT")
    assert "17.25" in exact.reason or "17,25" in exact.reason


def test_totals_traz_conversao_ao_lado_do_custo() -> None:
    """`total_cost_wasted_brl` mantem o nome; o desmentido vai na linha de baixo."""
    _kw, _st_out, _sug, totals, total_cost = match_competitor_brands(
        keyword_rows=[],
        search_term_rows=[_st(search_term="concorrente x", cost_brl=155.25, conversions=9.0)],
        competitor_brands=["concorrente"],
        limit=100,
    )
    assert total_cost == 155.25
    assert totals["total_conversions"] == 9.0
