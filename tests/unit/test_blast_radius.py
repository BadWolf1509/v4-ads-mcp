"""Parameterized tests covering all blast_radius rules from spec §7.1."""

import pytest

from src.governance.blast_radius import RiskLevel, classify

# (operation, params, expected_level, hint_substring_in_reason)
_CASES: list[tuple[str, dict, RiskLevel, str]] = [
    # Status changes — single
    ("update_campaign_status", {"target_count": 1}, RiskLevel.AUTO, "single"),
    ("update_ad_group_status", {"target_count": 1}, RiskLevel.AUTO, "single"),
    ("update_keyword_status", {"target_count": 1}, RiskLevel.AUTO, "single"),
    # Status changes — bulk small
    ("update_campaign_status", {"target_count": 3}, RiskLevel.AUTO, "bulk"),
    ("update_keyword_status", {"target_count": 5}, RiskLevel.AUTO, "bulk"),
    # Status changes — bulk large
    ("update_campaign_status", {"target_count": 6}, RiskLevel.CONFIRM, "more than 5"),
    ("update_ad_group_status", {"target_count": 50}, RiskLevel.CONFIRM, "more than 5"),
    # Budget always confirms
    ("update_campaign_budget", {"target_count": 1, "delta_pct": 5.0}, RiskLevel.CONFIRM, "budget"),
    ("update_campaign_budget", {"target_count": 1, "delta_pct": 0.1}, RiskLevel.CONFIRM, "budget"),
    # Bidding strategy always confirms
    ("update_campaign_bidding", {"target_count": 1}, RiskLevel.CONFIRM, "bidding"),
    # Bid changes — small variation
    ("update_keyword_bid", {"target_count": 1, "max_delta_pct": 10.0}, RiskLevel.AUTO, "small"),
    ("update_ad_group_bid", {"target_count": 5, "max_delta_pct": 19.5}, RiskLevel.AUTO, "small"),
    # Bid changes — large variation
    ("update_keyword_bid", {"target_count": 1, "max_delta_pct": 25.0}, RiskLevel.CONFIRM, "20%"),
    ("update_ad_group_bid", {"target_count": 1, "max_delta_pct": 21.0}, RiskLevel.CONFIRM, "20%"),
    # Bid changes — bulk
    (
        "update_keyword_bid",
        {"target_count": 6, "max_delta_pct": 5.0},
        RiskLevel.CONFIRM,
        "more than 5",
    ),
    # Negatives always auto
    ("add_negative_keywords", {"target_count": 100}, RiskLevel.AUTO, "negatives"),
    # add_negatives_from_search_terms — same rule as other negatives (AUTO)
    ("add_negatives_from_search_terms", {"target_count": 50}, RiskLevel.AUTO, "negatives"),
    ("add_negatives_from_search_terms", {"target_count": 500}, RiskLevel.AUTO, "negatives"),
    # Recommendations always auto
    ("apply_recommendation", {"target_count": 1}, RiskLevel.AUTO, "recommendation"),
    ("dismiss_recommendation", {"target_count": 1}, RiskLevel.AUTO, "recommendation"),
    # Sanity check: PAUSED still works
    ("update_ad_status", {"target_count": 1, "new_status": "PAUSED"}, RiskLevel.AUTO, "single"),
    # add_keywords — AUTO threshold is 20 per spec §7.1 (Add KWs ≤20 em 1 ad_group)
    ("add_keywords", {"target_count": 20}, RiskLevel.AUTO, "ad_group"),
    ("add_keywords", {"target_count": 21}, RiskLevel.CONFIRM, "20"),
    ("add_keywords", {"target_count": 100}, RiskLevel.CONFIRM, "20"),
    # apply_audience — observation: AUTO threshold 20 (matches add_keywords); exclusion: always CONFIRM
    (
        "apply_audience",
        {"target_count": 20, "mode": "observation"},
        RiskLevel.AUTO,
        "20 attachments",
    ),
    ("apply_audience", {"target_count": 21, "mode": "observation"}, RiskLevel.CONFIRM, "20"),
    ("apply_audience", {"target_count": 1, "mode": "exclusion"}, RiskLevel.CONFIRM, "exclusion"),
    ("apply_audience", {"target_count": 50, "mode": "exclusion"}, RiskLevel.CONFIRM, "exclusion"),
    # remove_audience — always CONFIRM (spec §7.1 remove principle), regardless of count
    ("remove_audience", {"target_count": 1}, RiskLevel.CONFIRM, "sempre confirma"),
    ("remove_audience", {"target_count": 50}, RiskLevel.CONFIRM, "sempre confirma"),
    # create_conversion_action — always CONFIRM (spec §7.1 creates sensitive; tracking affects ROAS)
    ("create_conversion_action", {"target_count": 1}, RiskLevel.CONFIRM, "spec §7.1"),
    ("create_conversion_action", {"target_count": 5}, RiskLevel.CONFIRM, "spec §7.1"),
    # create_conversion_value_rule_set — always CONFIRM (spec §7.1 creates sensitive; rules affect ROAS attribution)
    ("create_conversion_value_rule_set", {"target_count": 1}, RiskLevel.CONFIRM, "spec §7.1"),
    ("create_conversion_value_rule_set", {"target_count": 5}, RiskLevel.CONFIRM, "spec §7.1"),
]


@pytest.mark.parametrize("operation,params,expected_level,hint", _CASES)
def test_classify_returns_expected(operation, params, expected_level, hint):
    result = classify(operation=operation, params=params)
    assert result.level == expected_level, (
        f"{operation} with {params}: got {result.level}, expected {expected_level}"
    )
    assert hint.lower() in result.reason.lower(), (
        f"{operation}: reason '{result.reason}' missing hint '{hint}'"
    )


def test_unknown_operation_defaults_to_confirm():
    """Defensive: never auto-apply an unknown operation."""
    result = classify(operation="future_dangerous_tool", params={"target_count": 1})
    assert result.level == RiskLevel.CONFIRM
    assert "unknown" in result.reason.lower() or "default" in result.reason.lower()


def test_target_count_zero_is_confirm():
    """Edge case: target_count=0 means we don't know — be safe."""
    result = classify(operation="update_campaign_status", params={"target_count": 0})
    assert result.level == RiskLevel.CONFIRM


def test_missing_target_count_is_confirm():
    """Edge case: caller forgot to pass target_count."""
    result = classify(operation="update_keyword_bid", params={})
    assert result.level == RiskLevel.CONFIRM


class TestUpdateConversionActionClassify:
    def test_single_rename_only_is_auto(self):
        result = classify(
            operation="update_conversion_action",
            params={"updates": [{"conversion_action_id": "123", "name": "novo nome"}]},
        )
        assert result.level == RiskLevel.AUTO

    def test_single_disable_primary_for_goal_is_confirm(self):
        result = classify(
            operation="update_conversion_action",
            params={"updates": [{"conversion_action_id": "123", "primary_for_goal": False}]},
        )
        assert result.level == RiskLevel.CONFIRM

    def test_single_disable_include_in_metric_is_confirm(self):
        result = classify(
            operation="update_conversion_action",
            params={
                "updates": [{"conversion_action_id": "123", "include_in_conversions_metric": False}]
            },
        )
        assert result.level == RiskLevel.CONFIRM

    def test_batch_of_two_is_confirm_even_rename_only(self):
        result = classify(
            operation="update_conversion_action",
            params={
                "updates": [
                    {"conversion_action_id": "123", "name": "a"},
                    {"conversion_action_id": "456", "name": "b"},
                ]
            },
        )
        assert result.level == RiskLevel.CONFIRM

    def test_set_primary_for_goal_true_is_auto_for_single(self):
        """Setting True (enable) is safe — only False (disable) needs CONFIRM."""
        result = classify(
            operation="update_conversion_action",
            params={"updates": [{"conversion_action_id": "123", "primary_for_goal": True}]},
        )
        assert result.level == RiskLevel.AUTO
