from datetime import date
from types import SimpleNamespace

from src.google_ads.performance_breakdown import (
    _common_metrics,
    _validate_combo,
    build_performance_breakdown_query,
)


def test_validate_combo_entity_without_breakdown_ok():
    for level in ["campaign", "ad_group", "ad", "keyword", "audience"]:
        assert _validate_combo(level, None) is None


def test_validate_combo_account_with_breakdown_ok():
    for bd in ["device", "geo", "hourly"]:
        assert _validate_combo("account", bd) is None


def test_validate_combo_account_without_breakdown_rejected():
    msg = _validate_combo("account", None)
    assert msg is not None
    assert "get_account_overview" in msg


def test_validate_combo_entity_with_breakdown_rejected():
    msg = _validate_combo("campaign", "device")
    assert msg is not None
    assert "account" in msg.lower()


def test_common_metrics_happy():
    m = SimpleNamespace(
        impressions=100,
        clicks=10,
        cost_micros=5_000_000,
        conversions=1.0,
        conversions_value=50.0,
    )
    out = _common_metrics(m)
    assert out == {
        "impressions": 100,
        "clicks": 10,
        "cost_brl": 5.0,
        "conversions": 1.0,
        "conversions_value_brl": 50.0,
        "ctr": 0.1,
        "cpc_brl": 0.5,
    }


def test_common_metrics_zero_division():
    m = SimpleNamespace(
        impressions=0,
        clicks=0,
        cost_micros=0,
        conversions=0.0,
        conversions_value=0.0,
    )
    out = _common_metrics(m)
    assert out["ctr"] == 0.0
    assert out["cpc_brl"] == 0.0


_S, _E = date(2026, 1, 1), date(2026, 1, 31)


def test_build_query_entity_levels_from_clause():
    cases = {
        "campaign": "FROM campaign",
        "ad_group": "FROM ad_group",
        "ad": "FROM ad_group_ad",
        "keyword": "FROM keyword_view",
        "audience": "FROM ad_group_audience_view",
    }
    for level, frm in cases.items():
        q = build_performance_breakdown_query(level, None, "enabled", _S, _E, 100)
        assert frm in q


def test_build_query_account_breakdowns():
    q_dev = build_performance_breakdown_query("account", "device", "enabled", _S, _E, 100)
    assert "segments.device" in q_dev and "FROM customer" in q_dev
    q_geo = build_performance_breakdown_query("account", "geo", "enabled", _S, _E, 100)
    assert "geographic_view.country_criterion_id" in q_geo
    q_hr = build_performance_breakdown_query("account", "hourly", "enabled", _S, _E, 100)
    assert "segments.hour" in q_hr and "FROM customer" in q_hr


def test_build_query_status_applied_to_entity_with_status():
    q = build_performance_breakdown_query("campaign", None, "paused", _S, _E, 100)
    assert "campaign.status = 'PAUSED'" in q
