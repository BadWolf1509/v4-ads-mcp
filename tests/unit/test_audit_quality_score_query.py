"""Unit tests for src.google_ads.queries.audit_quality_score (Sprint 3b.30)."""

from src.google_ads.queries.audit_quality_score import build_audit_quality_score_query


def test_query_without_ad_group_filter():
    query = build_audit_quality_score_query(
        start_date="2026-04-20",
        end_date="2026-05-20",
        ad_group_ids=None,
    )
    assert "FROM keyword_view" in query
    assert "ad_group_criterion.status = 'ENABLED'" in query
    assert "ad_group_criterion.quality_info.quality_score IS NOT NULL" in query
    assert "segments.date BETWEEN '2026-04-20' AND '2026-05-20'" in query
    assert "ad_group.id IN" not in query  # no filter when None


def test_query_with_ad_group_filter_three_ids():
    query = build_audit_quality_score_query(
        start_date="2026-04-20",
        end_date="2026-05-20",
        ad_group_ids=["1001", "1002", "1003"],
    )
    assert "ad_group.id IN ('1001', '1002', '1003')" in query


def test_query_includes_status_enabled_and_qs_not_null():
    """Hardcoded filters MUST always be present (no opt-out)."""
    query = build_audit_quality_score_query(
        start_date="2026-04-20",
        end_date="2026-05-20",
        ad_group_ids=None,
    )
    assert "status = 'ENABLED'" in query
    assert "quality_score IS NOT NULL" in query


def test_query_with_custom_date_range_yyyy_mm_dd():
    query = build_audit_quality_score_query(
        start_date="2026-05-01",
        end_date="2026-05-14",
        ad_group_ids=None,
    )
    assert "segments.date BETWEEN '2026-05-01' AND '2026-05-14'" in query


def test_query_selects_all_required_fields():
    """Output must include all fields needed by KeywordRow dataclass."""
    query = build_audit_quality_score_query(
        start_date="2026-04-20",
        end_date="2026-05-20",
        ad_group_ids=None,
    )
    expected_fields = [
        "ad_group.id",
        "ad_group.name",
        "ad_group.status",  # A2 (espelha F52)
        "campaign.name",
        "ad_group_criterion.criterion_id",
        "ad_group_criterion.keyword.text",
        "ad_group_criterion.keyword.match_type",
        "ad_group_criterion.quality_info.quality_score",
        "metrics.impressions",
        "metrics.clicks",
        "metrics.conversions",
        "metrics.cost_micros",
    ]
    for f in expected_fields:
        assert f in query, f"Missing field: {f}"
