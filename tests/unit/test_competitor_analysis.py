"""Unit tests for src.google_ads.competitor_analysis (Sprint 3b.31)."""

from src.google_ads.competitor_analysis import (
    KeywordRow,
    SearchTermRow,
    match_competitor_brands,
    normalize_brand,
)


def _make_kw(
    *,
    ad_group_id: str = "1001",
    ad_group_name: str = "AG1",
    campaign_name: str = "C1",
    keyword_id: str = "1",
    keyword_text: str = "kw",
    match_type: str = "BROAD",
    # F90: default ENABLED preserva a semantica dos testes existentes (todos
    # assumiam keyword que compete); quem quiser o caso orfao passa explicito.
    ad_group_status: str = "ENABLED",
) -> KeywordRow:
    return KeywordRow(
        ad_group_id=ad_group_id,
        ad_group_name=ad_group_name,
        campaign_name=campaign_name,
        keyword_id=keyword_id,
        keyword_text=keyword_text,
        match_type=match_type,
        ad_group_status=ad_group_status,
    )


def _make_st(
    *,
    search_term: str = "st",
    ad_group_name: str = "AG1",
    campaign_name: str = "C1",
    impressions: int = 100,
    clicks: int = 5,
    cost_brl: float = 10.0,
) -> SearchTermRow:
    return SearchTermRow(
        search_term=search_term,
        ad_group_name=ad_group_name,
        campaign_name=campaign_name,
        impressions=impressions,
        clicks=clicks,
        cost_brl=cost_brl,
    )


def test_empty_inputs_returns_empty_everything():
    matched_kw, matched_st, suggested, totals, total_cost = match_competitor_brands(
        keyword_rows=[],
        search_term_rows=[],
        competitor_brands=[],
        limit=200,
    )
    assert matched_kw == []
    assert matched_st == []
    assert suggested == []
    assert totals == {
        "positive_count": 0,
        "positive_truncated": False,
        "search_count": 0,
        "search_truncated": False,
        "suggested_count": 0,
    }
    assert total_cost == 0.0


def test_normalize_brand_strips_and_lowercases():
    assert normalize_brand(" Projecta ") == "projecta"
    assert normalize_brand("CASA DO CONSTRUTOR") == "casa do construtor"
    assert normalize_brand("  promina") == "promina"


def test_positive_keyword_substring_match():
    rows = [_make_kw(keyword_text="comprar projecta gerador")]
    matched_kw, _, _, totals, _ = match_competitor_brands(
        keyword_rows=rows,
        search_term_rows=[],
        competitor_brands=["projecta"],
        limit=200,
    )
    assert len(matched_kw) == 1
    assert matched_kw[0].matched_brand == "projecta"
    assert matched_kw[0].status == "ENABLED"
    assert totals["positive_count"] == 1


def test_positive_keyword_case_insensitive():
    """Brand 'Projecta' matches kw 'PROJECTA 5500'."""
    rows = [_make_kw(keyword_text="PROJECTA 5500")]
    matched_kw, _, _, _, _ = match_competitor_brands(
        keyword_rows=rows,
        search_term_rows=[],
        competitor_brands=["Projecta"],
        limit=200,
    )
    assert len(matched_kw) == 1
    assert matched_kw[0].matched_brand == "projecta"


def test_no_matches_returns_empty_with_brands():
    """Brands passed mas zero matches → empty everything + no suggested."""
    rows = [_make_kw(keyword_text="kw normal sem brand")]
    matched_kw, matched_st, suggested, totals, total_cost = match_competitor_brands(
        keyword_rows=rows,
        search_term_rows=[_make_st(search_term="normal query")],
        competitor_brands=["projecta", "promina"],
        limit=200,
    )
    assert matched_kw == []
    assert matched_st == []
    assert suggested == []
    assert totals["positive_count"] == 0
    assert total_cost == 0.0


def test_search_term_match_aggregates_cost():
    """3 search_terms matched, costs [10, 20, 30] → total 60.0."""
    rows = [
        _make_st(search_term="gerador projecta 1", cost_brl=10.0),
        _make_st(search_term="projecta 5500", cost_brl=20.0),
        _make_st(search_term="comprar projecta", cost_brl=30.0),
    ]
    _, matched_st, _, _, total_cost = match_competitor_brands(
        keyword_rows=[],
        search_term_rows=rows,
        competitor_brands=["projecta"],
        limit=200,
    )
    assert len(matched_st) == 3
    assert total_cost == 60.0


def test_suggested_negatives_2_per_matched_brand():
    """1 brand matched → 2 sugestões (EXACT + PHRASE)."""
    rows = [_make_kw(keyword_text="comprar projecta")]
    _, _, suggested, _, _ = match_competitor_brands(
        keyword_rows=rows,
        search_term_rows=[],
        competitor_brands=["projecta"],
        limit=200,
    )
    assert len(suggested) == 2
    assert suggested[0].text == "projecta"
    assert suggested[0].match_type == "EXACT"
    assert suggested[1].text == "projecta"
    assert suggested[1].match_type == "PHRASE"


def test_suggested_negatives_skip_brand_without_matches():
    """Brand 'promina' passada mas zero match → NÃO incluída em suggested."""
    rows = [_make_kw(keyword_text="comprar projecta")]
    _, _, suggested, _, _ = match_competitor_brands(
        keyword_rows=rows,
        search_term_rows=[],
        competitor_brands=["projecta", "promina"],
        limit=200,
    )
    assert len(suggested) == 2  # Only projecta (EXACT + PHRASE)
    assert all(s.text == "projecta" for s in suggested)


def test_keyword_matched_by_first_brand_when_multiple_overlap():
    """Brands ['projecta', 'comprar'], kw 'comprar projecta' → matched_brand='projecta' (insertion order)."""
    rows = [_make_kw(keyword_text="comprar projecta")]
    matched_kw, _, _, _, _ = match_competitor_brands(
        keyword_rows=rows,
        search_term_rows=[],
        competitor_brands=["projecta", "comprar"],
        limit=200,
    )
    assert len(matched_kw) == 1
    assert matched_kw[0].matched_brand == "projecta"


def test_search_terms_sorted_by_cost_desc():
    """3 search_terms costs [50, 10, 30] → output [50, 30, 10]."""
    rows = [
        _make_st(search_term="projecta a", cost_brl=10.0),
        _make_st(search_term="projecta b", cost_brl=50.0),
        _make_st(search_term="projecta c", cost_brl=30.0),
    ]
    _, matched_st, _, _, _ = match_competitor_brands(
        keyword_rows=[],
        search_term_rows=rows,
        competitor_brands=["projecta"],
        limit=200,
    )
    assert [s.cost_brl for s in matched_st] == [50.0, 30.0, 10.0]


def test_truncate_positive_keywords_at_limit():
    """250 matches + limit=200 → 200 returned, totals=250."""
    rows = [_make_kw(keyword_id=str(i), keyword_text=f"projecta {i}") for i in range(250)]
    matched_kw, _, _, totals, _ = match_competitor_brands(
        keyword_rows=rows,
        search_term_rows=[],
        competitor_brands=["projecta"],
        limit=200,
    )
    assert len(matched_kw) == 200
    assert totals["positive_count"] == 250
    assert totals["positive_truncated"] is True


def test_truncate_search_terms_at_limit():
    """250 matched search_terms + limit=200 → 200 returned, totals=250."""
    rows = [_make_st(search_term=f"projecta {i}", cost_brl=1.0) for i in range(250)]
    _, matched_st, _, totals, _ = match_competitor_brands(
        keyword_rows=[],
        search_term_rows=rows,
        competitor_brands=["projecta"],
        limit=200,
    )
    assert len(matched_st) == 200
    assert totals["search_count"] == 250
    assert totals["search_truncated"] is True


def test_reason_string_includes_counts_and_cost():
    """Brand com 2 pos + 3 st (R$95.50) → reason text contém '2', '3', '95.50'."""
    pos_rows = [
        _make_kw(keyword_id="A", keyword_text="projecta 1"),
        _make_kw(keyword_id="B", keyword_text="comprar projecta"),
    ]
    st_rows = [
        _make_st(search_term="projecta a", cost_brl=30.0),
        _make_st(search_term="projecta b", cost_brl=25.50),
        _make_st(search_term="projecta c", cost_brl=40.0),
    ]
    _, _, suggested, _, _ = match_competitor_brands(
        keyword_rows=pos_rows,
        search_term_rows=st_rows,
        competitor_brands=["projecta"],
        limit=200,
    )
    exact = suggested[0]
    assert exact.match_type == "EXACT"
    assert "2 keyword" in exact.reason
    assert "3 search term" in exact.reason
    assert "95.50" in exact.reason


def test_brand_minimum_length_documented_not_enforced_at_pure_layer():
    """Brand 'MO' 2 chars passa em pure layer (schema upstream enforces minLength 3).

    Documenta contrato: validação de brand length é responsabilidade do schema,
    não do pure module. Tool MCP rejeita brand < 3 chars via input_schema.
    """
    rows = [_make_kw(keyword_text="MO equipamentos")]
    matched_kw, _, _, _, _ = match_competitor_brands(
        keyword_rows=rows,
        search_term_rows=[],
        competitor_brands=["MO"],
        limit=200,
    )
    assert len(matched_kw) == 1
