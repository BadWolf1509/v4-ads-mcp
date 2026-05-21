"""Unit tests for flag_zombie_keywords pure module (Sprint 3b.36)."""

from src.google_ads.flag_zombie_keywords import (
    KeywordRow,
    flag_zombie_keywords,
)


def _make_kw(
    *,
    ad_group_id: str = "1001",
    ad_group_name: str = "AG1",
    campaign_name: str = "C1",
    keyword_id: str = "K1",
    keyword_text: str = "andaime metálico",
    match_type: str = "BROAD",
    impressions: int = 0,
    clicks: int = 0,
    cost_brl: float = 0.0,
    conversions: int = 0,
    status: str = "ENABLED",
) -> KeywordRow:
    return KeywordRow(
        ad_group_id=ad_group_id,
        ad_group_name=ad_group_name,
        campaign_name=campaign_name,
        keyword_id=keyword_id,
        keyword_text=keyword_text,
        match_type=match_type,
        impressions=impressions,
        clicks=clicks,
        cost_brl=cost_brl,
        conversions=conversions,
        status=status,
    )


def test_empty_rows_returns_empty():
    zombies, total = flag_zombie_keywords([], limit=10)
    assert zombies == []
    assert total == 0


def test_filter_keeps_impressions_zero_clicks_zero():
    rows = [_make_kw(impressions=0, clicks=0)]
    zombies, total = flag_zombie_keywords(rows, limit=10)
    assert len(zombies) == 1
    assert total == 1


def test_filter_excludes_impressions_positive():
    """Keyword com impressions>0 NÃO é zombie (visible mas not clicked = outro issue)."""
    rows = [_make_kw(impressions=10, clicks=0)]
    zombies, total = flag_zombie_keywords(rows, limit=10)
    assert zombies == []
    assert total == 0


def test_filter_excludes_clicks_positive():
    """Keyword com clicks>0 NÃO é zombie (edge case: impressions=0 + clicks>0 rare mas defensive)."""
    rows = [_make_kw(impressions=0, clicks=1)]
    zombies, total = flag_zombie_keywords(rows, limit=10)
    assert zombies == []
    assert total == 0


def test_sort_by_ad_group_name_asc():
    rows = [
        _make_kw(keyword_id="A", ad_group_name="Zulu Group", keyword_text="alpha"),
        _make_kw(keyword_id="B", ad_group_name="Alpha Group", keyword_text="beta"),
        _make_kw(keyword_id="C", ad_group_name="Mike Group", keyword_text="gamma"),
    ]
    zombies, _ = flag_zombie_keywords(rows, limit=10)
    ad_groups = [z.ad_group_name for z in zombies]
    assert ad_groups == ["Alpha Group", "Mike Group", "Zulu Group"]


def test_sort_tie_break_by_keyword_text_asc():
    rows = [
        _make_kw(keyword_id="A", ad_group_name="Same AG", keyword_text="zulu"),
        _make_kw(keyword_id="B", ad_group_name="Same AG", keyword_text="alpha"),
        _make_kw(keyword_id="C", ad_group_name="Same AG", keyword_text="mike"),
    ]
    zombies, _ = flag_zombie_keywords(rows, limit=10)
    texts = [z.keyword_text for z in zombies]
    assert texts == ["alpha", "mike", "zulu"]


def test_truncation_limit_exceeded():
    """50 zombies + limit=10 → returns 10, total=50."""
    rows = [_make_kw(keyword_id=str(i), keyword_text=f"kw_{i:03d}") for i in range(50)]
    zombies, total = flag_zombie_keywords(rows, limit=10)
    assert len(zombies) == 10
    assert total == 50


def test_truncation_limit_not_exceeded():
    """5 zombies + limit=200 → returns 5, total=5."""
    rows = [_make_kw(keyword_id=str(i)) for i in range(5)]
    zombies, total = flag_zombie_keywords(rows, limit=200)
    assert len(zombies) == 5
    assert total == 5


def test_multiple_keywords_same_ad_group_all_listed():
    rows = [
        _make_kw(keyword_id="A", ad_group_name="Same AG", keyword_text="alpha"),
        _make_kw(keyword_id="B", ad_group_name="Same AG", keyword_text="beta"),
        _make_kw(keyword_id="C", ad_group_name="Same AG", keyword_text="gamma"),
    ]
    zombies, total = flag_zombie_keywords(rows, limit=10)
    assert len(zombies) == 3
    assert total == 3


def test_total_count_pre_truncate_preserved():
    """Mix de zombies + non-zombies: total reflete POST-filter, PRE-truncate."""
    rows = [
        _make_kw(keyword_id="A", impressions=0, clicks=0),  # zombie
        _make_kw(keyword_id="B", impressions=10, clicks=0),  # not zombie (visible)
        _make_kw(keyword_id="C", impressions=0, clicks=0),  # zombie
        _make_kw(keyword_id="D", impressions=100, clicks=5),  # not zombie (active)
    ]
    zombies, total = flag_zombie_keywords(rows, limit=10)
    assert len(zombies) == 2
    assert total == 2  # only the 2 zombies count
