"""Unit tests for BUC (X-Business-Use-Case-Usage) header parsing (Sprint M.2a Task 7)."""

import json

from src.governance.rate_limit import _parse_buc_header_pct


def test_parse_buc_extracts_max_pct():
    """Returns max(call_count, total_cputime, total_time) for matching ad_account."""
    header = json.dumps(
        {
            "123456789": [
                {
                    "type": "ads_management",
                    "call_count": 42,
                    "total_cputime": 12,
                    "total_time": 35,
                    "estimated_time_to_regain_access": 0,
                }
            ]
        }
    )
    pct = _parse_buc_header_pct(header, ad_account_id="act_123456789")
    assert pct == 42  # max(42, 12, 35)


def test_parse_buc_returns_zero_when_account_not_in_header():
    header = json.dumps(
        {"999": [{"type": "ads_read", "call_count": 50, "total_cputime": 0, "total_time": 0}]}
    )
    pct = _parse_buc_header_pct(header, ad_account_id="act_111")
    assert pct == 0


def test_parse_buc_handles_empty_header():
    pct = _parse_buc_header_pct("", ad_account_id="act_123")
    assert pct == 0


def test_parse_buc_handles_empty_json():
    pct = _parse_buc_header_pct("{}", ad_account_id="act_123")
    assert pct == 0


def test_parse_buc_handles_malformed_json():
    pct = _parse_buc_header_pct("not valid json", ad_account_id="act_123")
    assert pct == 0


def test_parse_buc_strips_act_prefix():
    """ad_account_id 'act_111' should match key '111' in BUC JSON."""
    header = json.dumps({"111": [{"call_count": 75, "total_cputime": 5, "total_time": 5}]})
    pct = _parse_buc_header_pct(header, ad_account_id="act_111")
    assert pct == 75


def test_parse_buc_multiple_usage_entries():
    """If BUC has multiple entries for same ad_account, take max across all."""
    header = json.dumps(
        {
            "123": [
                {"call_count": 30, "total_cputime": 10, "total_time": 20},
                {"call_count": 90, "total_cputime": 50, "total_time": 60},
            ]
        }
    )
    pct = _parse_buc_header_pct(header, ad_account_id="act_123")
    assert pct == 90
