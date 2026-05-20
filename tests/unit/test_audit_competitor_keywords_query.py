"""Unit tests for src.google_ads.queries.audit_competitor_keywords (Sprint 3b.31)."""

from src.google_ads.queries.audit_competitor_keywords import (
    build_positive_keywords_query,
    build_search_terms_query,
)


def test_positive_keywords_query_includes_status_enabled_and_negative_false():
    query = build_positive_keywords_query()
    assert "FROM keyword_view" in query
    assert "ad_group_criterion.status = 'ENABLED'" in query
    assert "ad_group_criterion.negative = FALSE" in query


def test_positive_keywords_query_no_date_filter():
    """State-based query — sem segments.date BETWEEN."""
    query = build_positive_keywords_query()
    assert "segments.date" not in query
    assert "BETWEEN" not in query


def test_search_terms_query_includes_date_between():
    query = build_search_terms_query(start_date="2026-05-13", end_date="2026-05-19")
    assert "FROM search_term_view" in query
    assert "segments.date BETWEEN '2026-05-13' AND '2026-05-19'" in query


def test_positive_keywords_query_selects_required_fields():
    """6 fields necessários pra KeywordRow."""
    query = build_positive_keywords_query()
    expected_fields = [
        "ad_group.id",
        "ad_group.name",
        "campaign.name",
        "ad_group_criterion.criterion_id",
        "ad_group_criterion.keyword.text",
        "ad_group_criterion.keyword.match_type",
    ]
    for f in expected_fields:
        assert f in query, f"Missing field: {f}"


def test_search_terms_query_selects_required_fields():
    """6 fields necessários pra SearchTermRow."""
    query = build_search_terms_query(start_date="2026-05-13", end_date="2026-05-19")
    expected_fields = [
        "search_term_view.search_term",
        "ad_group.name",
        "campaign.name",
        "metrics.impressions",
        "metrics.clicks",
        "metrics.cost_micros",
    ]
    for f in expected_fields:
        assert f in query, f"Missing field: {f}"


def test_parse_keyword_row_handles_match_type_enum():
    """match_type.name extrai string enum (BROAD/PHRASE/EXACT)."""
    from unittest.mock import MagicMock

    from src.google_ads.queries.audit_competitor_keywords import parse_positive_keyword_row

    fake_row = MagicMock()
    fake_row.ad_group.id = 1001
    fake_row.ad_group.name = "AG1"
    fake_row.campaign.name = "C1"
    fake_row.ad_group_criterion.criterion_id = 42
    fake_row.ad_group_criterion.keyword.text = "comprar projecta"
    fake_row.ad_group_criterion.keyword.match_type.name = "BROAD"

    parsed = parse_positive_keyword_row(fake_row)
    assert parsed["ad_group_id"] == "1001"
    assert parsed["keyword_id"] == "42"
    assert parsed["keyword_text"] == "comprar projecta"
    assert parsed["match_type"] == "BROAD"
