"""Unit tests for src.google_ads.queries.keyword_lookup (Sprint 3b.40 A1)."""

import pytest

from src.google_ads.queries.keyword_lookup import (
    _lookup_row_formatter,
    build_keyword_text_lookup_query,
)


def test_build_query_dedups_and_sorts_ids():
    """Pairs com duplicates → IN clause dedupes, output ordered ASC."""
    pairs = [
        ("1001", "K2"),
        ("1002", "K1"),
        ("1001", "K3"),
        ("1001", "K2"),  # duplicate
    ]
    query = build_keyword_text_lookup_query(pairs)
    assert "FROM ad_group_criterion" in query
    # Dedup + sort
    assert "ad_group.id IN (1001, 1002)" in query
    assert "ad_group_criterion.criterion_id IN (K1, K2, K3)" in query
    # No date filter (resource is absolute state)
    assert "segments.date" not in query


def test_build_query_selects_required_fields():
    pairs = [("1001", "K1")]
    query = build_keyword_text_lookup_query(pairs)
    expected_fields = [
        "ad_group.id",
        "ad_group_criterion.criterion_id",
        "ad_group_criterion.keyword.text",
        "ad_group_criterion.keyword.match_type",
    ]
    for f in expected_fields:
        assert f in query, f"Missing field: {f}"


def test_build_query_empty_pairs_raises():
    with pytest.raises(ValueError, match="cannot be empty"):
        build_keyword_text_lookup_query([])


def test_lookup_row_formatter_extracts_fields():
    """Mock SDK row → dict with str types pra ids."""

    class FakeKeyword:
        text = "aluguel de airless"

        class match_type:  # noqa: N801
            name = "BROAD"

    class FakeCriterion:
        criterion_id = 12345
        keyword = FakeKeyword()

    class FakeAdGroup:
        id = 67890

    class FakeRow:
        ad_group = FakeAdGroup()
        ad_group_criterion = FakeCriterion()

    out = _lookup_row_formatter(FakeRow())
    assert out["ad_group_id"] == "67890"
    assert out["criterion_id"] == "12345"
    assert out["keyword_text"] == "aluguel de airless"
    assert out["match_type"] == "BROAD"
