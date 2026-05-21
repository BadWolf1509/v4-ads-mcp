"""Unit tests for flag_orphan_smart_actions pure module (Sprint 3b.37)."""

from src.google_ads.flag_orphan_smart_actions import (
    ConversionActionRow,
    flag_orphan_smart_actions,
)


def _make_ca(
    *,
    conversion_action_id: str = "1001",
    name: str = "Whatsapp - JPA",
    category: str = "CONTACT",
    origin: str = "WEBSITE",
    primary_for_goal: bool = True,
    status: str = "ENABLED",
    all_conversions: float = 0.0,
) -> ConversionActionRow:
    return ConversionActionRow(
        conversion_action_id=conversion_action_id,
        name=name,
        category=category,
        origin=origin,
        primary_for_goal=primary_for_goal,
        status=status,
        all_conversions=all_conversions,
    )


def test_empty_rows_returns_empty():
    orphans, total = flag_orphan_smart_actions([], limit=10)
    assert orphans == []
    assert total == 0


def test_filter_keeps_zero_conversions():
    rows = [_make_ca(all_conversions=0.0)]
    orphans, total = flag_orphan_smart_actions(rows, limit=10)
    assert len(orphans) == 1
    assert total == 1


def test_filter_excludes_positive_conversions():
    """ConversionAction com >0 conversions NÃO é orphan."""
    rows = [_make_ca(all_conversions=5.0)]
    orphans, total = flag_orphan_smart_actions(rows, limit=10)
    assert orphans == []
    assert total == 0


def test_filter_excludes_fractional_conversions():
    """ConversionAction com 0.5 conversions NÃO é orphan (Google can return fractional)."""
    rows = [_make_ca(all_conversions=0.5)]
    orphans, total = flag_orphan_smart_actions(rows, limit=10)
    assert orphans == []
    assert total == 0


def test_sort_by_category_origin_name():
    rows = [
        _make_ca(conversion_action_id="A", category="PURCHASE", origin="WEBSITE", name="Zulu"),
        _make_ca(
            conversion_action_id="B", category="CONTACT", origin="CALL_FROM_ADS", name="Alpha"
        ),
        _make_ca(conversion_action_id="C", category="CONTACT", origin="WEBSITE", name="Mike"),
        _make_ca(conversion_action_id="D", category="CONTACT", origin="WEBSITE", name="Alpha"),
    ]
    orphans, _ = flag_orphan_smart_actions(rows, limit=10)
    keys = [(o.category, o.origin, o.name) for o in orphans]
    assert keys == [
        ("CONTACT", "CALL_FROM_ADS", "Alpha"),
        ("CONTACT", "WEBSITE", "Alpha"),
        ("CONTACT", "WEBSITE", "Mike"),
        ("PURCHASE", "WEBSITE", "Zulu"),
    ]


def test_truncation_limit_exceeded():
    """50 orphans + limit=10 → returns 10, total=50."""
    rows = [_make_ca(conversion_action_id=str(i), name=f"ca_{i:03d}") for i in range(50)]
    orphans, total = flag_orphan_smart_actions(rows, limit=10)
    assert len(orphans) == 10
    assert total == 50


def test_truncation_limit_not_exceeded():
    """5 orphans + limit=200 → returns 5, total=5."""
    rows = [_make_ca(conversion_action_id=str(i)) for i in range(5)]
    orphans, total = flag_orphan_smart_actions(rows, limit=200)
    assert len(orphans) == 5
    assert total == 5


def test_total_count_pre_truncate_preserved():
    """Mix de orphans + non-orphans: total reflete POST-filter, PRE-truncate."""
    rows = [
        _make_ca(conversion_action_id="A", all_conversions=0.0),  # orphan
        _make_ca(conversion_action_id="B", all_conversions=3.0),  # not orphan
        _make_ca(conversion_action_id="C", all_conversions=0.0),  # orphan
        _make_ca(conversion_action_id="D", all_conversions=12.5),  # not orphan
    ]
    orphans, total = flag_orphan_smart_actions(rows, limit=10)
    assert len(orphans) == 2
    assert total == 2  # only 2 orphans
