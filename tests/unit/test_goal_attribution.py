"""Unit tests for goal_attribution pure module (Sprint 3b.35)."""

from src.google_ads.goal_attribution import (
    ConversionActionRow,
    CustomerConversionGoalRow,
    audit_goal_attribution,
)


def _make_action(
    *,
    id: str = "1",
    name: str = "Whatsapp - JPA",
    category: str = "CONTACT",
    origin: str = "WEBSITE",
    primary_for_goal: bool = False,
    include_in_conversions_metric: bool = True,
    status: str = "ENABLED",
) -> ConversionActionRow:
    return ConversionActionRow(
        id=id,
        name=name,
        category=category,
        origin=origin,
        primary_for_goal=primary_for_goal,
        include_in_conversions_metric=include_in_conversions_metric,
        status=status,
    )


def _make_goal(
    *,
    category: str = "CONTACT",
    origin: str = "WEBSITE",
    biddable: bool = True,
) -> CustomerConversionGoalRow:
    return CustomerConversionGoalRow(category=category, origin=origin, biddable=biddable)


def test_empty_actions_returns_empty_summary():
    result = audit_goal_attribution(
        actions=[], goals=[], category_filter=None, customer_id="1234567890"
    )
    assert result.origin_summary == {}
    assert result.total_actions_audited == 0
    assert result.origins_audited == ()
    assert result.categories_audited == ()


def test_paused_action_excluded():
    result = audit_goal_attribution(
        actions=[_make_action(status="PAUSED")],
        goals=[_make_goal()],
        category_filter=None,
        customer_id="1234567890",
    )
    assert result.total_actions_audited == 0
    assert result.origin_summary == {}


def test_removed_action_excluded():
    result = audit_goal_attribution(
        actions=[_make_action(status="REMOVED")],
        goals=[_make_goal()],
        category_filter=None,
        customer_id="1234567890",
    )
    assert result.total_actions_audited == 0


def test_category_filter_match_keeps_action():
    result = audit_goal_attribution(
        actions=[_make_action(category="CONTACT")],
        goals=[_make_goal()],
        category_filter="CONTACT",
        customer_id="1234567890",
    )
    assert result.total_actions_audited == 1
    assert "WEBSITE" in result.origin_summary


def test_category_filter_no_match_excludes_action():
    result = audit_goal_attribution(
        actions=[_make_action(category="PURCHASE")],
        goals=[_make_goal(category="PURCHASE")],
        category_filter="CONTACT",
        customer_id="1234567890",
    )
    assert result.total_actions_audited == 0
    assert result.origin_summary == {}


def test_no_filter_groups_all_categories_composite_key():
    """Sem category_filter, key = '{cat}__{origin}' composite."""
    result = audit_goal_attribution(
        actions=[
            _make_action(category="CONTACT", origin="WEBSITE"),
            _make_action(id="2", category="PURCHASE", origin="WEBSITE"),
        ],
        goals=[_make_goal(category="CONTACT"), _make_goal(category="PURCHASE")],
        category_filter=None,
        customer_id="1234567890",
    )
    assert "CONTACT__WEBSITE" in result.origin_summary
    assert "PURCHASE__WEBSITE" in result.origin_summary


def test_filter_set_uses_origin_only_key():
    """Com category_filter, key = origin simple."""
    result = audit_goal_attribution(
        actions=[_make_action(category="CONTACT", origin="WEBSITE")],
        goals=[_make_goal()],
        category_filter="CONTACT",
        customer_id="1234567890",
    )
    assert "WEBSITE" in result.origin_summary
    assert "CONTACT__WEBSITE" not in result.origin_summary


def test_primary_for_goal_true_in_primary_bucket():
    result = audit_goal_attribution(
        actions=[_make_action(primary_for_goal=True, name="Primary Action")],
        goals=[_make_goal()],
        category_filter="CONTACT",
        customer_id="1234567890",
    )
    summary = result.origin_summary["WEBSITE"]
    assert summary.primary_count == 1
    assert summary.secondary_count == 0
    assert summary.primary_actions[0].name == "Primary Action"


def test_primary_for_goal_false_in_secondary_bucket():
    result = audit_goal_attribution(
        actions=[_make_action(primary_for_goal=False, name="Secondary Action")],
        goals=[_make_goal()],
        category_filter="CONTACT",
        customer_id="1234567890",
    )
    summary = result.origin_summary["WEBSITE"]
    assert summary.primary_count == 0
    assert summary.secondary_count == 1
    assert summary.secondary_actions[0].name == "Secondary Action"


def test_biddable_true_emits_warning_pt():
    result = audit_goal_attribution(
        actions=[_make_action()],
        goals=[_make_goal(biddable=True)],
        category_filter="CONTACT",
        customer_id="1234567890",
    )
    summary = result.origin_summary["WEBSITE"]
    assert summary.biddable is True
    assert summary.warning is not None
    assert "AFETA Smart Bidding" in summary.warning


def test_biddable_false_warning_is_null():
    result = audit_goal_attribution(
        actions=[_make_action()],
        goals=[_make_goal(biddable=False)],
        category_filter="CONTACT",
        customer_id="1234567890",
    )
    summary = result.origin_summary["WEBSITE"]
    assert summary.biddable is False
    assert summary.warning is None


def test_goal_absent_for_origin_defaults_biddable_false():
    """Action sem customer_conversion_goal correspondente → biddable=False default."""
    result = audit_goal_attribution(
        actions=[_make_action(origin="APP")],
        goals=[_make_goal(origin="WEBSITE")],  # APP missing
        category_filter="CONTACT",
        customer_id="1234567890",
    )
    summary = result.origin_summary["APP"]
    assert summary.biddable is False
    assert summary.warning is None


def test_multiple_actions_same_origin_all_listed():
    """Multiple actions com mesmo (cat, origin) → todas em primary OU secondary."""
    result = audit_goal_attribution(
        actions=[
            _make_action(id="1", name="A", primary_for_goal=True),
            _make_action(id="2", name="B", primary_for_goal=True),
            _make_action(id="3", name="C", primary_for_goal=False),
        ],
        goals=[_make_goal()],
        category_filter="CONTACT",
        customer_id="1234567890",
    )
    summary = result.origin_summary["WEBSITE"]
    assert summary.primary_count == 2
    assert summary.secondary_count == 1


def test_actions_sorted_by_name_asc_in_primary():
    result = audit_goal_attribution(
        actions=[
            _make_action(id="1", name="Zebra", primary_for_goal=True),
            _make_action(id="2", name="Alpha", primary_for_goal=True),
            _make_action(id="3", name="Mike", primary_for_goal=True),
        ],
        goals=[_make_goal()],
        category_filter="CONTACT",
        customer_id="1234567890",
    )
    summary = result.origin_summary["WEBSITE"]
    names = [a.name for a in summary.primary_actions]
    assert names == ["Alpha", "Mike", "Zebra"]


def test_actions_sorted_by_name_asc_in_secondary():
    result = audit_goal_attribution(
        actions=[
            _make_action(id="1", name="Zulu", primary_for_goal=False),
            _make_action(id="2", name="Charlie", primary_for_goal=False),
        ],
        goals=[_make_goal()],
        category_filter="CONTACT",
        customer_id="1234567890",
    )
    summary = result.origin_summary["WEBSITE"]
    names = [a.name for a in summary.secondary_actions]
    assert names == ["Charlie", "Zulu"]


def test_metadata_total_audited_counts_post_filter():
    """total_actions_audited reflete POST-status-filter + POST-category-filter."""
    result = audit_goal_attribution(
        actions=[
            _make_action(id="1", status="ENABLED", category="CONTACT"),
            _make_action(id="2", status="PAUSED", category="CONTACT"),
            _make_action(id="3", status="ENABLED", category="PURCHASE"),
        ],
        goals=[_make_goal()],
        category_filter="CONTACT",
        customer_id="1234567890",
    )
    assert result.total_actions_audited == 1  # só id=1 passa ambos filters


def test_metadata_origins_audited_unique_sorted():
    result = audit_goal_attribution(
        actions=[
            _make_action(id="1", origin="WEBSITE"),
            _make_action(id="2", origin="APP"),
            _make_action(id="3", origin="WEBSITE"),
        ],
        goals=[_make_goal()],
        category_filter="CONTACT",
        customer_id="1234567890",
    )
    assert result.origins_audited == ("APP", "WEBSITE")


def test_metadata_categories_audited_unique_sorted():
    result = audit_goal_attribution(
        actions=[
            _make_action(id="1", category="PURCHASE"),
            _make_action(id="2", category="CONTACT"),
            _make_action(id="3", category="CONTACT"),
        ],
        goals=[_make_goal()],
        category_filter=None,
        customer_id="1234567890",
    )
    assert result.categories_audited == ("CONTACT", "PURCHASE")
