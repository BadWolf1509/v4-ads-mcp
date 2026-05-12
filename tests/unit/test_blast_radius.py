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
    # REMOVED status always confirms (spec §7.1: "Remove qualquer coisa = sempre confirm")
    (
        "update_campaign_status",
        {"target_count": 1, "new_status": "REMOVED"},
        RiskLevel.CONFIRM,
        "remove",
    ),
    (
        "update_ad_group_status",
        {"target_count": 1, "new_status": "REMOVED"},
        RiskLevel.CONFIRM,
        "remove",
    ),
    (
        "update_keyword_status",
        {"target_count": 3, "new_status": "REMOVED"},
        RiskLevel.CONFIRM,
        "remove",
    ),
    ("update_ad_status", {"target_count": 1, "new_status": "REMOVED"}, RiskLevel.CONFIRM, "remove"),
    ("update_ad_status", {"target_count": 1, "new_status": "PAUSED"}, RiskLevel.AUTO, "single"),
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
