"""Unit tests for audit_zombie_keywords GAQL builder + boundary parser (Sprint 3b.36)."""

from types import SimpleNamespace

from src.google_ads.queries.audit_zombie_keywords import (
    build_audit_zombie_keywords_query,
    dict_to_keyword_row,
    parse_keyword_view_row,
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
        "ad_group.status",  # F52: revelar órfãs em ad_group REMOVED
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
    assert row.ad_group_status == ""  # F52
    assert row.impressions == 0
    assert row.clicks == 0
    assert row.cost_brl == 0.0
    assert row.conversions == 0
    assert row.status == ""


def test_parse_keyword_view_row_handles_enums_and_micros():
    """Boundary parser uses .name on enums (3b.7 lesson) + cost_micros division.

    Regression guard against:
    - proto-plus v20+ regression (str(enum) returns int, .name returns 'BROAD'/'ENABLED')
    - cost_micros / 1_000_000.0 conversion
    - int casting on ad_group.id + criterion_id
    - F52: ad_group.status enum unwrap via .name
    """
    fake_row = SimpleNamespace(
        ad_group_criterion=SimpleNamespace(
            criterion_id=12345,
            keyword=SimpleNamespace(
                text="andaime metálico",
                match_type=SimpleNamespace(name="BROAD"),
            ),
            status=SimpleNamespace(name="ENABLED"),
        ),
        ad_group=SimpleNamespace(
            id=1001,
            name="AG1",
            status=SimpleNamespace(name="ENABLED"),  # F52
        ),
        campaign=SimpleNamespace(name="C1"),
        metrics=SimpleNamespace(
            impressions=0,
            clicks=0,
            cost_micros=0,
            conversions=0,
        ),
    )
    result = parse_keyword_view_row(fake_row)
    assert result["keyword_id"] == "12345"  # int → str
    assert result["ad_group_id"] == "1001"  # int → str
    assert result["ad_group_status"] == "ENABLED"  # F52 .name resolution
    assert result["match_type"] == "BROAD"  # .name resolution
    assert result["status"] == "ENABLED"  # .name resolution
    assert result["cost_brl"] == 0.0  # cost_micros / 1_000_000.0
    assert result["keyword_text"] == "andaime metálico"


def test_parse_keyword_view_row_orphan_ad_group_removed():
    """F52 scenario: keyword ENABLED em ad_group REMOVED é órfã cosmética.

    Reproduz pegadinha do dogfood 2026-05-25 MO-JP+CAB: tool retornava 280
    zombies mas 170 (60.7%) eram órfãs em DELL JPA + GPA02 ANDAIME CAB
    (ad_groups REMOVED) — keywords não competem em leilão, batch PAUSE no-op.
    """
    fake_row = SimpleNamespace(
        ad_group_criterion=SimpleNamespace(
            criterion_id=999,
            keyword=SimpleNamespace(
                text="dell notebook",
                match_type=SimpleNamespace(name="BROAD"),
            ),
            status=SimpleNamespace(name="ENABLED"),
        ),
        ad_group=SimpleNamespace(
            id=174842025340,
            name="DELL",
            status=SimpleNamespace(name="REMOVED"),  # órfã cosmética
        ),
        campaign=SimpleNamespace(name="JPA"),
        metrics=SimpleNamespace(impressions=0, clicks=0, cost_micros=0, conversions=0),
    )
    result = parse_keyword_view_row(fake_row)
    assert result["ad_group_status"] == "REMOVED"
    assert result["status"] == "ENABLED"  # keyword ENABLED mas ad_group REMOVED
    assert result["ad_group_name"] == "DELL"
