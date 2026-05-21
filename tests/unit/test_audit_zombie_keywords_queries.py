"""Unit tests for audit_zombie_keywords GAQL builder + boundary parser (Sprint 3b.36)."""

from src.google_ads.queries.audit_zombie_keywords import (
    build_audit_zombie_keywords_query,
    dict_to_keyword_row,
)


def test_build_query_includes_required_fields():
    q = build_audit_zombie_keywords_query(
        start_date="2026-04-21",
        end_date="2026-05-21",
        ad_group_ids=None,
    )
    required_fields = [
        "ad_group_criterion.criterion_id",
        "ad_group_criterion.keyword.text",
        "ad_group_criterion.keyword.match_type",
        "ad_group_criterion.status",
        "ad_group.id",
        "ad_group.name",
        "campaign.name",
        "metrics.impressions",
        "metrics.clicks",
        "metrics.cost_micros",
        "metrics.conversions",
    ]
    for field in required_fields:
        assert field in q
    assert "FROM keyword_view" in q


def test_build_query_filters_enabled_and_not_negative():
    q = build_audit_zombie_keywords_query(
        start_date="2026-04-21",
        end_date="2026-05-21",
        ad_group_ids=None,
    )
    assert "ad_group_criterion.status = 'ENABLED'" in q
    assert "ad_group_criterion.negative = FALSE" in q


def test_build_query_ad_group_ids_filter():
    q = build_audit_zombie_keywords_query(
        start_date="2026-04-21",
        end_date="2026-05-21",
        ad_group_ids=["123", "456"],
    )
    assert "ad_group.id IN (123,456)" in q


def test_dict_to_keyword_row_handles_missing_fields():
    """Boundary parser defensive defaults."""
    d: dict = {"keyword_text": "test"}
    row = dict_to_keyword_row(d)
    assert row.keyword_text == "test"
    assert row.ad_group_id == ""
    assert row.impressions == 0
    assert row.clicks == 0
    assert row.cost_brl == 0.0
    assert row.conversions == 0
    assert row.status == ""
