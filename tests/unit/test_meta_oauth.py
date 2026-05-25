"""Unit tests for Meta OAuth callback decision tree (Sprint M.2a Task 8)."""

from src.auth.meta_oauth import check_meta_granted_scopes


def test_check_granted_scopes_accepts_all_essentials():
    granted = {"ads_read", "ads_management", "business_management", "email", "public_profile"}
    missing = check_meta_granted_scopes(granted)
    assert missing == set()


def test_check_granted_scopes_blocks_missing_ads_read():
    granted = {"ads_management", "email", "public_profile"}
    missing = check_meta_granted_scopes(granted)
    assert missing == {"ads_read"}


def test_check_granted_scopes_blocks_missing_ads_management():
    granted = {"ads_read", "email"}
    missing = check_meta_granted_scopes(granted)
    assert missing == {"ads_management"}


def test_check_granted_scopes_blocks_missing_both_essentials():
    granted = {"email", "public_profile"}
    missing = check_meta_granted_scopes(granted)
    assert missing == {"ads_read", "ads_management"}


def test_check_granted_scopes_ignores_business_management_when_essentials_present():
    """business_management is declared but NOT essential — missing it doesn't block."""
    granted = {"ads_read", "ads_management", "email"}
    missing = check_meta_granted_scopes(granted)
    assert missing == set()
