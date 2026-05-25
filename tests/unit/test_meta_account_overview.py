"""Unit tests pure module src/meta_ads/account_overview.py (Sprint M.2b)."""

from datetime import UTC, date, datetime

import pytest

from src.meta_ads.account_overview import (
    build_warnings,
    compute_deltas,
    parse_insights_response,
    resolve_meta_date_window,
    shift_to_previous_period,
)

TODAY = date(2026, 5, 25)


class TestResolveDateWindow:
    """resolve_meta_date_window tests."""

    def test_resolve_date_window_default_last_7_days(self):
        start, end = resolve_meta_date_window(None, None, None, TODAY)
        assert start == date(2026, 5, 19)
        assert end == TODAY

    def test_resolve_date_window_last_30_days(self):
        start, end = resolve_meta_date_window("LAST_30_DAYS", None, None, TODAY)
        assert start == date(2026, 4, 26)
        assert end == TODAY

    def test_resolve_date_window_today(self):
        start, end = resolve_meta_date_window("TODAY", None, None, TODAY)
        assert start == TODAY == end

    def test_resolve_date_window_yesterday(self):
        start, end = resolve_meta_date_window("YESTERDAY", None, None, TODAY)
        assert start == date(2026, 5, 24)
        assert end == date(2026, 5, 24)

    def test_resolve_date_window_custom_overrides_preset(self):
        start, end = resolve_meta_date_window("LAST_7_DAYS", "2026-05-01", "2026-05-10", TODAY)
        assert start == date(2026, 5, 1)
        assert end == date(2026, 5, 10)

    def test_resolve_date_window_partial_custom_start_only_raises(self):
        with pytest.raises(ValueError, match="start_date e end_date devem ser fornecidos juntos"):
            resolve_meta_date_window(None, "2026-05-01", None, TODAY)

    def test_resolve_date_window_partial_custom_end_only_raises(self):
        with pytest.raises(ValueError, match="start_date e end_date devem ser fornecidos juntos"):
            resolve_meta_date_window(None, None, "2026-05-10", TODAY)


class TestShiftPreviousPeriod:
    """shift_to_previous_period tests."""

    def test_shift_previous_7_day_window(self):
        prev_start, prev_end = shift_to_previous_period(date(2026, 5, 19), date(2026, 5, 25))
        assert prev_start == date(2026, 5, 12)
        assert prev_end == date(2026, 5, 18)

    def test_shift_previous_single_day(self):
        prev_start, prev_end = shift_to_previous_period(date(2026, 5, 25), date(2026, 5, 25))
        assert prev_start == date(2026, 5, 24)
        assert prev_end == date(2026, 5, 24)

    def test_shift_previous_30_day_window(self):
        prev_start, prev_end = shift_to_previous_period(date(2026, 4, 26), date(2026, 5, 25))
        assert prev_start == date(2026, 3, 27)
        assert prev_end == date(2026, 4, 25)


class TestParseInsightsResponse:
    """parse_insights_response tests."""

    def test_parse_insights_empty_data(self):
        result = parse_insights_response({"data": []})
        assert result["spend"] == 0.0
        assert result["impressions"] == 0
        assert result["conversions"] == 0

    def test_parse_insights_no_data_key(self):
        result = parse_insights_response({})
        assert result["spend"] == 0.0

    def test_parse_insights_full_row(self):
        data = {
            "data": [
                {
                    "spend": "1234.56",
                    "impressions": "45000",
                    "clicks": "1200",
                    "ctr": "2.67",
                    "cpc": "1.03",
                    "reach": "23000",
                    "frequency": "1.95",
                    "actions": [
                        {"action_type": "purchase", "value": "35"},
                        {"action_type": "link_click", "value": "1200"},  # NOT counted
                        {"action_type": "lead", "value": "5"},
                    ],
                    "action_values": [
                        {"action_type": "purchase", "value": "8400.0"},
                        {"action_type": "link_click", "value": "0"},  # NOT counted
                    ],
                    "purchase_roas": [{"action_type": "omni_purchase", "value": "6.8"}],
                }
            ]
        }
        result = parse_insights_response(data)
        assert result["spend"] == 1234.56
        assert result["impressions"] == 45000
        assert result["clicks"] == 1200
        assert result["ctr"] == 2.67
        assert result["cpc"] == 1.03
        assert result["reach"] == 23000
        assert result["frequency"] == 1.95
        assert result["conversions"] == 40  # 35 purchase + 5 lead
        assert result["conversion_value"] == 8400.0
        assert result["purchase_roas"] == 6.8

    def test_parse_insights_fb_pixel_action_types_counted(self):
        """offsite_conversion.fb_pixel_* MUST be counted (Meta tracking)."""
        data = {
            "data": [
                {
                    "spend": "100",
                    "actions": [
                        {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "10"},
                        {"action_type": "offsite_conversion.fb_pixel_lead", "value": "3"},
                    ],
                }
            ]
        }
        result = parse_insights_response(data)
        assert result["conversions"] == 13

    def test_parse_insights_missing_purchase_roas_returns_zero(self):
        data = {"data": [{"spend": "100"}]}
        result = parse_insights_response(data)
        assert result["purchase_roas"] == 0.0

    def test_parse_insights_null_values_handled(self):
        """Meta às vezes retorna null pra fields ausentes."""
        data = {"data": [{"spend": None, "impressions": None, "actions": None}]}
        result = parse_insights_response(data)
        assert result["spend"] == 0.0
        assert result["impressions"] == 0
        assert result["conversions"] == 0

    def test_parse_insights_complete_register_action_type(self):
        """complete_registration também é action_type countable."""
        data = {
            "data": [
                {
                    "spend": "100",
                    "actions": [
                        {"action_type": "complete_registration", "value": "8"},
                    ],
                }
            ]
        }
        result = parse_insights_response(data)
        assert result["conversions"] == 8

    def test_parse_insights_multiple_roas_entries_first_purchase_wins(self):
        """purchase_roas array pode ter múltiplas entradas, retorna primeira purchase/omni_purchase."""
        data = {
            "data": [
                {
                    "purchase_roas": [
                        {"action_type": "link_click", "value": "1.5"},
                        {"action_type": "purchase", "value": "4.2"},
                        {"action_type": "omni_purchase", "value": "5.0"},
                    ]
                }
            ]
        }
        result = parse_insights_response(data)
        assert result["purchase_roas"] == 4.2  # purchase encontrado primeiro


class TestComputeDeltas:
    """compute_deltas tests."""

    def test_compute_deltas_growth(self):
        current = {"spend": 1200.0, "conversions": 40}
        previous = {"spend": 1000.0, "conversions": 30}
        deltas = compute_deltas(current, previous)
        assert deltas["spend_pct"] == 20.0
        assert round(deltas["conversions_pct"], 2) == 33.33

    def test_compute_deltas_decline(self):
        current = {"spend": 800.0, "conversions": 25}
        previous = {"spend": 1000.0, "conversions": 30}
        deltas = compute_deltas(current, previous)
        assert deltas["spend_pct"] == -20.0
        assert round(deltas["conversions_pct"], 2) == -16.67

    def test_compute_deltas_previous_zero_returns_none(self):
        current = {"spend": 100.0, "conversions": 5}
        previous = {"spend": 0.0, "conversions": 0}
        deltas = compute_deltas(current, previous)
        assert deltas["spend_pct"] is None
        assert deltas["conversions_pct"] is None

    def test_compute_deltas_missing_keys_zero(self):
        current = {"spend": 100.0}
        previous = {"spend": 50.0, "conversions": 10}
        deltas = compute_deltas(current, previous)
        assert deltas["spend_pct"] == 100.0
        assert deltas["conversions_pct"] == -100.0

    def test_compute_deltas_returns_all_expected_keys(self):
        current = {
            "spend": 100,
            "impressions": 1000,
            "clicks": 50,
            "conversions": 5,
            "conversion_value": 500,
            "purchase_roas": 5.0,
        }
        previous = {
            "spend": 100,
            "impressions": 1000,
            "clicks": 50,
            "conversions": 5,
            "conversion_value": 500,
            "purchase_roas": 5.0,
        }
        deltas = compute_deltas(current, previous)
        expected_keys = {
            "spend_pct",
            "impressions_pct",
            "clicks_pct",
            "conversions_pct",
            "conversion_value_pct",
            "purchase_roas_pct",
        }
        assert set(deltas.keys()) == expected_keys

    def test_compute_deltas_zero_percent_change(self):
        """Dados iguais → 0.0 não None."""
        current = {"spend": 500.0}
        previous = {"spend": 500.0}
        deltas = compute_deltas(current, previous)
        assert deltas["spend_pct"] == 0.0


class TestBuildWarnings:
    """build_warnings tests."""

    def test_build_warnings_ativo_token_fresh_returns_empty(self):
        now = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
        token_expires = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
        warnings = build_warnings("ATIVO", token_expires, now)
        assert warnings == []

    def test_build_warnings_account_pagamento_pendente(self):
        now = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
        token_expires = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
        warnings = build_warnings("PAGAMENTO_PENDENTE", token_expires, now)
        assert len(warnings) == 1
        assert "PAGAMENTO_PENDENTE" in warnings[0]

    def test_build_warnings_account_fechado(self):
        now = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
        token_expires = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
        warnings = build_warnings("FECHADO", token_expires, now)
        assert len(warnings) == 1
        assert "FECHADO" in warnings[0]

    def test_build_warnings_token_expires_in_5_days(self):
        now = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
        token_expires = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
        warnings = build_warnings("ATIVO", token_expires, now)
        assert len(warnings) == 1
        assert "5 dias" in warnings[0]
        assert "2026-05-30" in warnings[0]
        assert "Reconectar" in warnings[0]

    def test_build_warnings_token_expires_in_6_days_still_warns(self):
        now = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
        token_expires = datetime(2026, 5, 31, 12, 0, tzinfo=UTC)
        warnings = build_warnings("ATIVO", token_expires, now)
        assert len(warnings) == 1

    def test_build_warnings_token_expires_in_7_days_no_warn(self):
        """7d exactly → não warning ainda (strictly less than)."""
        now = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
        token_expires = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        warnings = build_warnings("ATIVO", token_expires, now)
        assert warnings == []

    def test_build_warnings_token_none_no_warn(self):
        now = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
        warnings = build_warnings("ATIVO", None, now)
        assert warnings == []

    def test_build_warnings_both_warnings_present(self):
        now = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
        token_expires = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
        warnings = build_warnings("PAGAMENTO_PENDENTE", token_expires, now)
        assert len(warnings) == 2

    def test_build_warnings_account_suspenso(self):
        now = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
        token_expires = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
        warnings = build_warnings("SUSPENSO", token_expires, now)
        assert len(warnings) == 1
        assert "SUSPENSO" in warnings[0]
