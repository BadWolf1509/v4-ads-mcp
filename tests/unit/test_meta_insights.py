"""Unit tests for src/meta_ads/insights.py (Sprint M.3 Task 2).

Pure module — zero IO, zero SDK. ~50ms total.
"""

from datetime import date

from src.meta_ads.insights import (
    _extract_action_value,
    _extract_purchase_roas,
    build_insights_call,
    parse_insights_row,
)  # noqa: F401

# ============================================================================
# build_insights_call
# ============================================================================


def test_build_insights_call_campaign_level() -> None:
    edge, params = build_insights_call(
        level="campaign",
        ad_account_id="act_123",
        start=date(2026, 5, 1),
        end=date(2026, 5, 7),
        limit=100,
    )
    assert edge == "/act_123/insights"
    assert params["level"] == "campaign"
    assert "spend" in params["fields"]
    assert "campaign_id" in params["fields"]
    assert "objective" in params["fields"]
    assert params["time_range"] == '{"since":"2026-05-01","until":"2026-05-07"}'
    assert params["limit"] == 100
    assert params["ad_account_id"] == "act_123"
    # M.3.1 (F53): effective_status filter removido — Meta Insights API rejeita
    assert "filtering" not in params
    assert "effective_status" not in params["fields"]


def test_build_insights_call_adset_level() -> None:
    _, params = build_insights_call(
        level="adset",
        ad_account_id="act_456",
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        limit=50,
    )
    assert params["level"] == "adset"
    assert "adset_id" in params["fields"]
    assert "optimization_goal" in params["fields"]
    # M.3.1.1 (F54): billing_event + daily_budget removed (Meta Insights rejects)
    assert "billing_event" not in params["fields"]
    assert "daily_budget" not in params["fields"]
    assert "effective_status" not in params["fields"]


def test_build_insights_call_ad_level() -> None:
    _, params = build_insights_call(
        level="ad",
        ad_account_id="act_789",
        start=date(2026, 5, 25),
        end=date(2026, 5, 25),
        limit=500,
    )
    assert params["level"] == "ad"
    assert "ad_id" in params["fields"]
    assert params["limit"] == 500
    # M.3.1.1 (F54): creative_id removed (Meta Insights rejects)
    assert "creative_id" not in params["fields"]
    assert "effective_status" not in params["fields"]


def test_build_insights_call_never_injects_filtering() -> None:
    """M.3.1 hotfix (F53): filtering block removed entirely. NEVER injected."""
    _, params = build_insights_call(
        level="campaign",
        ad_account_id="act_1",
        start=date(2026, 5, 1),
        end=date(2026, 5, 1),
        limit=10,
    )
    assert "filtering" not in params


# ============================================================================
# parse_insights_row — campaign level
# ============================================================================


def test_parse_insights_row_campaign_full() -> None:
    row = {
        "campaign_id": "23842",
        "campaign_name": "Brand BR",
        "objective": "OUTCOME_SALES",
        "effective_status": "ACTIVE",
        "spend": "1234.56",
        "impressions": "50000",
        "clicks": "800",
        "ctr": "1.6",
        "cpc": "1.54",
        "reach": "12345",
        "frequency": "4.05",
        "actions": [
            {"action_type": "purchase", "value": "12"},
            {"action_type": "lead", "value": "3"},
        ],
        "action_values": [{"action_type": "purchase", "value": "5500.00"}],
        "purchase_roas": [{"action_type": "omni_purchase", "value": "4.45"}],
    }
    out = parse_insights_row(row, "campaign")
    assert out["campaign_id"] == "23842"
    assert out["campaign_name"] == "Brand BR"
    assert out["objective"] == "OUTCOME_SALES"
    assert out["effective_status"] == "ACTIVE"
    assert out["effective_status_label"] == "ATIVO"
    assert out["spend_brl"] == 1234.56
    assert out["impressions"] == 50000
    assert out["clicks"] == 800
    assert out["ctr"] == 0.016  # 1.6% → decimal
    assert out["cpc_brl"] == 1.54
    assert out["reach"] == 12345
    assert out["frequency"] == 4.05
    assert out["purchases"] == 12
    assert out["purchases_value_brl"] == 5500.00
    assert out["purchase_roas"] == 4.45
    assert out["leads"] == 3


# ============================================================================
# parse_insights_row — adset level
# ============================================================================


def test_parse_insights_row_adset_with_daily_budget() -> None:
    row = {
        "adset_id": "12345",
        "adset_name": "AS 1",
        "campaign_id": "23842",
        "campaign_name": "Brand BR",
        "optimization_goal": "OFFSITE_CONVERSIONS",
        "billing_event": "IMPRESSIONS",
        "daily_budget": "5000",  # cents = R$50.00
        "effective_status": "ACTIVE",
        "spend": "100",
        "impressions": "1000",
        "clicks": "50",
    }
    out = parse_insights_row(row, "adset")
    assert out["ad_set_id"] == "12345"
    assert out["ad_set_name"] == "AS 1"
    assert out["campaign_id"] == "23842"
    assert out["optimization_goal"] == "OFFSITE_CONVERSIONS"
    assert out["billing_event"] == "IMPRESSIONS"
    assert out["daily_budget_brl"] == 50.00


def test_parse_insights_row_adset_no_daily_budget() -> None:
    """CBO campaigns: ad sets sem daily_budget → None."""
    row = {
        "adset_id": "12345",
        "adset_name": "AS 1",
        "campaign_id": "23842",
        "campaign_name": "Brand BR",
        "effective_status": "PAUSED",
    }
    out = parse_insights_row(row, "adset")
    assert out["daily_budget_brl"] is None


# ============================================================================
# parse_insights_row — ad level
# ============================================================================


def test_parse_insights_row_ad_missing_optional() -> None:
    """Ad sem creative_id → None acceptable, não fatal."""
    row = {
        "ad_id": "99999",
        "ad_name": "Ad 1",
        "adset_id": "12345",
        "adset_name": "AS 1",
        "campaign_id": "23842",
        "campaign_name": "Brand BR",
        "effective_status": "ACTIVE",
        # creative_id absent
    }
    out = parse_insights_row(row, "ad")
    assert out["ad_id"] == "99999"
    assert out["creative_id"] is None
    assert out["effective_status_label"] == "ATIVO"


# ============================================================================
# parse_insights_row — edge cases common
# ============================================================================


def test_parse_insights_row_no_actions() -> None:
    """Row sem actions → purchases=0, leads=0, purchases_value_brl=0."""
    row = {
        "campaign_id": "1",
        "campaign_name": "Test",
        "effective_status": "ACTIVE",
        "spend": "100",
    }
    out = parse_insights_row(row, "campaign")
    assert out["purchases"] == 0
    assert out["purchases_value_brl"] == 0.0
    assert out["leads"] == 0
    assert out["purchase_roas"] == 0.0


def test_parse_insights_row_ctr_normalization() -> None:
    """Meta ctr é percentual (1.6 = 1.6%) → decimal (0.016)."""
    row = {
        "campaign_id": "1",
        "campaign_name": "T",
        "effective_status": "ACTIVE",
        "ctr": "2.5",  # 2.5%
    }
    out = parse_insights_row(row, "campaign")
    assert out["ctr"] == 0.025


def test_parse_insights_row_unknown_effective_status() -> None:
    """Status fora do mapa → label='DESCONHECIDO'."""
    row = {
        "campaign_id": "1",
        "campaign_name": "T",
        "effective_status": "BIZARRE_NEW_STATUS",
    }
    out = parse_insights_row(row, "campaign")
    assert out["effective_status"] == "BIZARRE_NEW_STATUS"
    assert out["effective_status_label"] == "DESCONHECIDO"


# ============================================================================
# _extract_action_value helper
# ============================================================================


def test_extract_action_value_missing_action_type() -> None:
    actions = [{"action_type": "link_click", "value": "100"}]
    assert _extract_action_value(actions, "purchase") == 0.0


def test_extract_action_value_first_match_only() -> None:
    """Se houver múltiplos action_type='purchase', retorna primeiro encontrado."""
    actions = [
        {"action_type": "purchase", "value": "10"},
        {"action_type": "purchase", "value": "20"},
    ]
    assert _extract_action_value(actions, "purchase") == 10.0


def test_extract_action_value_malformed_value() -> None:
    """Value não-numérico → 0 (defensive)."""
    actions = [{"action_type": "purchase", "value": "not_a_number"}]
    assert _extract_action_value(actions, "purchase") == 0.0


def test_extract_action_value_none_or_empty() -> None:
    assert _extract_action_value(None, "purchase") == 0.0
    assert _extract_action_value([], "purchase") == 0.0


# ============================================================================
# _extract_purchase_roas helper
# ============================================================================


def test_extract_purchase_roas_first_only() -> None:
    """purchase_roas é lista; retorna [0].value."""
    roas = [
        {"action_type": "omni_purchase", "value": "4.45"},
        {"action_type": "purchase", "value": "5.00"},  # ignored
    ]
    assert _extract_purchase_roas(roas) == 4.45


def test_extract_purchase_roas_empty_list() -> None:
    assert _extract_purchase_roas([]) == 0.0
    assert _extract_purchase_roas(None) == 0.0
