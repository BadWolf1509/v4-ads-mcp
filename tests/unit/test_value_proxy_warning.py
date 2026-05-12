"""Sanity tests for the value_proxy_warning helper."""

from src.google_ads.queries._common import value_proxy_warning


def test_warning_returned_on_1_to_1_ratio():
    """conversions_value == conversions → warning returned with key phrases."""
    warning = value_proxy_warning(93.0, 93.0)
    assert warning is not None
    assert "1:1 ratio" in warning
    assert "misleading" in warning.lower()


def test_no_warning_when_value_exceeds_count():
    """Real revenue tracking (value > count): no warning."""
    assert value_proxy_warning(10.0, 250.50) is None


def test_no_warning_when_value_less_than_count():
    """Partial value tracking (some conversions have R$ 0 value): no warning."""
    assert value_proxy_warning(10.0, 5.0) is None


def test_no_warning_when_zero_conversions():
    """Edge case: zero conversions = vacuous 0/0 — no warning (no signal yet)."""
    assert value_proxy_warning(0.0, 0.0) is None


def test_warning_with_fractional_conversions():
    """Smart bidding fractional conversions (e.g., 7.5) — still applies if 1:1."""
    assert value_proxy_warning(7.5, 7.5) is not None
    assert value_proxy_warning(7.5, 7.51) is None  # very small mismatch = no 1:1
