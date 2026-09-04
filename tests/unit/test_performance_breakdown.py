from datetime import date
from types import SimpleNamespace

from src.google_ads.performance_breakdown import (
    _common_metrics,
    _validate_combo,
    build_performance_breakdown_query,
    parse_performance_row,
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


def _enum(name):
    return SimpleNamespace(name=name)


def _metrics():
    return SimpleNamespace(
        impressions=100,
        clicks=10,
        cost_micros=5_000_000,
        conversions=1.0,
        conversions_value=50.0,
    )


def test_parse_campaign():
    row = SimpleNamespace(
        campaign=SimpleNamespace(
            id=10,
            name="C1",
            status=_enum("ENABLED"),
            advertising_channel_type=_enum("SEARCH"),
        ),
        metrics=_metrics(),
    )
    out = parse_performance_row(row, "campaign", None)
    assert out["campaign_id"] == "10"
    assert out["campaign_name"] == "C1"
    assert out["status"] == "ENABLED"
    assert out["type"] == "SEARCH"
    assert out["cost_brl"] == 5.0 and out["ctr"] == 0.1


def test_parse_ad_group():
    row = SimpleNamespace(
        ad_group=SimpleNamespace(id=1001, name="AG1", status=_enum("ENABLED")),
        campaign=SimpleNamespace(id=10, name="C1"),
        metrics=_metrics(),
    )
    out = parse_performance_row(row, "ad_group", None)
    assert out["ad_group_id"] == "1001" and out["ad_group_name"] == "AG1"
    assert out["status"] == "ENABLED" and out["campaign_id"] == "10"


def test_parse_ad_rsa_assets():
    ad = SimpleNamespace(
        id=7,
        type=_enum("RESPONSIVE_SEARCH_AD"),
        responsive_search_ad=SimpleNamespace(
            headlines=[SimpleNamespace(text="H1"), SimpleNamespace(text="H2")],
            descriptions=[SimpleNamespace(text="D1")],
        ),
        final_urls=["https://x.com"],
    )
    row = SimpleNamespace(
        ad_group_ad=SimpleNamespace(ad=ad, status=_enum("ENABLED"), ad_strength=_enum("GOOD")),
        ad_group=SimpleNamespace(id=1001, name="AG1"),
        campaign=SimpleNamespace(id=10, name="C1"),
        metrics=_metrics(),
    )
    out = parse_performance_row(row, "ad", None)
    assert out["ad_id"] == "7" and out["ad_strength"] == "GOOD"
    assert out["headlines"] == ["H1", "H2"] and out["descriptions"] == ["D1"]
    assert out["final_urls"] == ["https://x.com"]


def test_parse_keyword_quality():
    row = SimpleNamespace(
        ad_group_criterion=SimpleNamespace(
            criterion_id=12345,
            keyword=SimpleNamespace(text="airless", match_type=_enum("BROAD")),
            status=_enum("ENABLED"),
            negative=False,
            quality_info=SimpleNamespace(
                quality_score=7,
                creative_quality_score=_enum("ABOVE_AVERAGE"),
                post_click_quality_score=_enum("AVERAGE"),
                search_predicted_ctr=_enum("BELOW_AVERAGE"),
            ),
            position_estimates=SimpleNamespace(
                first_page_cpc_micros=500_000,
                top_of_page_cpc_micros=1_200_000,
            ),
        ),
        ad_group=SimpleNamespace(id=1001, name="AG1"),
        campaign=SimpleNamespace(id=10, name="C1"),
        metrics=_metrics(),
    )
    out = parse_performance_row(row, "keyword", None)
    assert out["criterion_id"] == "12345" and out["keyword_text"] == "airless"
    assert out["match_type"] == "BROAD" and out["negative"] is False
    assert out["quality_score"] == 7 and out["first_page_cpc_brl"] == 0.5


def test_parse_audience():
    row = SimpleNamespace(
        ad_group_audience_view=SimpleNamespace(resource_name="customers/1/x"),
        ad_group_criterion=SimpleNamespace(
            criterion_id=55,
            user_list=SimpleNamespace(user_list="customers/1/userLists/9"),
            user_interest=SimpleNamespace(user_interest_category=""),
        ),
        ad_group=SimpleNamespace(id=1001, name="AG1"),
        campaign=SimpleNamespace(id=10, name="C1"),
        metrics=_metrics(),
    )
    out = parse_performance_row(row, "audience", None)
    assert out["criterion_id"] == "55"
    assert out["user_list"] == "customers/1/userLists/9"
    assert out["user_interest_category"] is None


def test_parse_account_device():
    row = SimpleNamespace(segments=SimpleNamespace(device=_enum("MOBILE")), metrics=_metrics())
    out = parse_performance_row(row, "account", "device")
    assert out["breakdown"] == {"device": "MOBILE"}
    assert out["cost_brl"] == 5.0


def test_parse_account_geo():
    row = SimpleNamespace(
        geographic_view=SimpleNamespace(country_criterion_id=2076), metrics=_metrics()
    )
    out = parse_performance_row(row, "account", "geo")
    assert out["breakdown"] == {"country_criterion_id": "2076"}


def test_parse_account_hourly():
    row = SimpleNamespace(
        segments=SimpleNamespace(hour=11, day_of_week=_enum("MONDAY")), metrics=_metrics()
    )
    out = parse_performance_row(row, "account", "hourly")
    assert out["breakdown"] == {"hour": 11, "day_of_week": "MONDAY"}


def test_campaign_mais_hourly_deixa_de_ser_recusado():
    assert _validate_combo("campaign", "hourly") is None


def test_outros_breakdowns_seguem_recusados_em_entity_level():
    """Só `hourly` abriu. `geo` continua fora: é regra de merge, não nível."""
    assert _validate_combo("campaign", "geo") is not None
    assert _validate_combo("ad_group", "hourly") is not None
