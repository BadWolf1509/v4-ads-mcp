"""Unit tests for src.google_ads.flag_keywords.flag_keywords (Sprint 3b.30).

Pure function tests — sem Google SDK fixture. Cobertura: 3 flags + duplicate
amplification + sort + truncate.
"""

from src.google_ads.flag_keywords import KeywordRow, flag_keywords


def _make_row(
    *,
    ad_group_id: str = "1001",
    ad_group_name: str = "AG1",
    ad_group_status: str = "ENABLED",  # A2 (espelha F52)
    campaign_name: str = "C1",
    keyword_id: str = "1",
    keyword_text: str = "kw",
    match_type: str = "BROAD",
    quality_score: int = 5,
    impressions: int = 100,
    clicks: int = 5,
    conversions: int = 0,
    cost_brl: float = 0.0,
) -> KeywordRow:
    return KeywordRow(
        ad_group_id=ad_group_id,
        ad_group_name=ad_group_name,
        ad_group_status=ad_group_status,  # A2 (espelha F52)
        campaign_name=campaign_name,
        keyword_id=keyword_id,
        keyword_text=keyword_text,
        match_type=match_type,
        quality_score=quality_score,
        impressions=impressions,
        clicks=clicks,
        conversions=conversions,
        cost_brl=cost_brl,
    )


def test_f52_pattern_ad_group_status_propagates_to_flagged_keyword():
    """A2 (espelha F52): ad_group_status field propaga de KeywordRow → FlaggedKeyword."""
    row = _make_row(
        ad_group_status="REMOVED",
        quality_score=2,
        impressions=15,
        clicks=0,
    )
    flagged, _ = flag_keywords([row], min_impressions=10, limit=200)
    assert len(flagged) == 1
    assert flagged[0].ad_group_status == "REMOVED"


def test_empty_rows_returns_empty():
    flagged, total = flag_keywords([], min_impressions=10, limit=200)
    assert flagged == []
    assert total == 0


def test_candidate_pause_flagged_when_qs_low_imp_above_threshold_zero_clicks():
    row = _make_row(quality_score=2, impressions=15, clicks=0)
    flagged, total = flag_keywords([row], min_impressions=10, limit=200)
    assert len(flagged) == 1
    assert flagged[0].flags == ("candidate_pause",)
    assert total == 1


def test_candidate_pause_not_flagged_when_impressions_below_threshold():
    row = _make_row(quality_score=2, impressions=5, clicks=0)
    flagged, total = flag_keywords([row], min_impressions=10, limit=200)
    assert flagged == []
    assert total == 0


def test_candidate_pause_not_flagged_when_qs_3():
    row = _make_row(quality_score=3, impressions=100, clicks=0)
    flagged, total = flag_keywords([row], min_impressions=10, limit=200)
    assert flagged == []


def test_candidate_pause_not_flagged_when_clicks_above_zero():
    row = _make_row(quality_score=1, impressions=100, clicks=2)
    flagged, total = flag_keywords([row], min_impressions=10, limit=200)
    assert flagged == []


def test_candidate_promote_exact_flagged_when_qs_high_broad_with_conversions():
    row = _make_row(quality_score=8, match_type="BROAD", conversions=2)
    flagged, total = flag_keywords([row], min_impressions=10, limit=200)
    assert len(flagged) == 1
    assert flagged[0].flags == ("candidate_promote_exact",)


def test_candidate_promote_exact_not_flagged_when_already_exact():
    row = _make_row(quality_score=9, match_type="EXACT", conversions=5)
    flagged, total = flag_keywords([row], min_impressions=10, limit=200)
    assert flagged == []


def test_candidate_promote_exact_not_flagged_zero_conversions():
    row = _make_row(quality_score=9, match_type="BROAD", conversions=0)
    flagged, total = flag_keywords([row], min_impressions=10, limit=200)
    assert flagged == []


def test_duplicate_intent_amplifies_existing_pause():
    rows = [
        _make_row(
            ad_group_id="1001",
            keyword_id="A",
            keyword_text="gerador energia",
            quality_score=2,
            impressions=50,
            clicks=0,
        ),
        _make_row(
            ad_group_id="1002",
            keyword_id="B",
            keyword_text="gerador energia",
            quality_score=1,
            impressions=30,
            clicks=0,
        ),
    ]
    flagged, _ = flag_keywords(rows, min_impressions=10, limit=200)
    assert len(flagged) == 2
    for f in flagged:
        assert "candidate_pause" in f.flags
        assert "duplicate_intent" in f.flags


def test_duplicate_intent_amplifies_promote():
    rows = [
        _make_row(
            ad_group_id="1001",
            keyword_id="A",
            keyword_text="gerador honda",
            quality_score=8,
            match_type="BROAD",
            conversions=2,
        ),
        _make_row(
            ad_group_id="1002",
            keyword_id="B",
            keyword_text="gerador honda",
            quality_score=9,
            match_type="BROAD",
            conversions=3,
        ),
    ]
    flagged, _ = flag_keywords(rows, min_impressions=10, limit=200)
    assert len(flagged) == 2
    for f in flagged:
        assert "candidate_promote_exact" in f.flags
        assert "duplicate_intent" in f.flags


def test_duplicate_intent_not_added_without_other_flag():
    """2 kw 'Y' em ad_groups diff, ambas QS=5 normal -> NOT flagged (amplificacao only)."""
    rows = [
        _make_row(ad_group_id="1001", keyword_text="kw normal", quality_score=5),
        _make_row(ad_group_id="1002", keyword_text="kw normal", quality_score=5),
    ]
    flagged, total = flag_keywords(rows, min_impressions=10, limit=200)
    assert flagged == []
    assert total == 0


def test_duplicate_intent_not_added_same_ad_group():
    """Mesma kw 2x em mesmo ad_group -> NAO conta como duplicate."""
    rows = [
        _make_row(
            ad_group_id="1001",
            keyword_id="A",
            keyword_text="kw same",
            quality_score=2,
            impressions=15,
            clicks=0,
        ),
        _make_row(
            ad_group_id="1001",
            keyword_id="B",
            keyword_text="kw same",
            quality_score=1,
            impressions=20,
            clicks=0,
        ),
    ]
    flagged, _ = flag_keywords(rows, min_impressions=10, limit=200)
    assert len(flagged) == 2
    for f in flagged:
        assert f.flags == ("candidate_pause",)  # no duplicate_intent


def test_sort_qs_asc_then_impressions_desc():
    """3 kw QS=2 com imp variando -> impressions DESC tie-break."""
    rows = [
        _make_row(keyword_id="A", quality_score=2, impressions=10, clicks=0),
        _make_row(keyword_id="B", quality_score=2, impressions=50, clicks=0),
        _make_row(keyword_id="C", quality_score=2, impressions=30, clicks=0),
    ]
    flagged, _ = flag_keywords(rows, min_impressions=5, limit=200)
    assert [f.keyword_id for f in flagged] == ["B", "C", "A"]


def test_truncate_at_limit_returns_total_pre_truncate():
    """250 flagged + limit=200 -> 200 returned, total=250."""
    rows = [
        _make_row(
            keyword_id=str(i),
            keyword_text=f"kw_{i}",  # unique text - no duplicate_intent
            quality_score=2,
            impressions=20,
            clicks=0,
        )
        for i in range(250)
    ]
    flagged, total = flag_keywords(rows, min_impressions=10, limit=200)
    assert len(flagged) == 200
    assert total == 250


def test_candidate_pause_flagged_at_impressions_boundary_equals_threshold():
    """Boundary: impressions == min_impressions deve flagar (>=, não >)."""
    row = _make_row(quality_score=2, impressions=10, clicks=0)
    flagged, total = flag_keywords([row], min_impressions=10, limit=200)
    assert len(flagged) == 1
    assert flagged[0].flags == ("candidate_pause",)
    assert total == 1


def test_candidate_promote_exact_flagged_at_qs_boundary_7():
    """Boundary: QS == 7 deve flagar (>=, não >)."""
    row = _make_row(quality_score=7, match_type="BROAD", conversions=1)
    flagged, total = flag_keywords([row], min_impressions=10, limit=200)
    assert len(flagged) == 1
    assert flagged[0].flags == ("candidate_promote_exact",)
    assert total == 1
