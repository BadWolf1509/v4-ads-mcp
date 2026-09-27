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
from tests.unit._meta_formas_medidas import LINHA_COMPRA_E_LEAD, LINHA_SO_CONVERSAS

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
    """parse_insights_response — as metricas do periodo pelo contrato (spec 2026-09-26).

    Os testes anteriores afirmavam a regra que o spec revoga: zero para campo ausente
    (`conversions == 0`, `purchase_roas == 0.0`), `ctr` em porcentagem, e a SOMA de
    seis nomes de conversao — que conta o mesmo evento varias vezes quando a Meta
    devolve os recortes (medido: a mesma compra sob 5 nomes, o mesmo lead sob 7).
    """

    def test_sem_linha_entrega_zero_eventos_null_e_marcador(self):
        """M7: sem entrega, a Meta nao manda linha — nao manda linha zerada."""
        for data in ({"data": []}, {}):
            result = parse_insights_response(data)
            assert result["sem_dados_no_periodo"] is True
            assert result["spend_brl"] == 0.0
            assert result["impressions"] == 0
            assert result["purchases"] is None
            assert result["leads"] is None
            assert result["ctr"] is None

    def test_linha_medida_sai_pelo_contrato(self):
        result = parse_insights_response({"data": [LINHA_COMPRA_E_LEAD]})
        assert result["sem_dados_no_periodo"] is False
        assert result["spend_brl"] == 22662.53
        assert result["purchases"] == 10
        assert result["leads"] == 13
        assert result["messaging_conversations_started"] == 3531
        assert result["ctr"] == 0.0178  # fracao, como o trio e o Google
        assert result["purchase_roas"] is None  # M4: nao veio

    def test_nao_ha_mais_soma_de_conversoes(self):
        """`conversions`/`conversion_value` saem: somavam recortes do mesmo evento."""
        result = parse_insights_response({"data": [LINHA_COMPRA_E_LEAD]})
        assert "conversions" not in result
        assert "conversion_value" not in result

    def test_mesmas_chaves_do_trio(self):
        """Um contrato so: o overview e o trio falam os mesmos nomes."""
        from src.meta_ads.metricas import metricas_da_linha

        result = parse_insights_response({"data": [LINHA_SO_CONVERSAS]})
        assert set(result) == set(metricas_da_linha({})) | {"sem_dados_no_periodo"}


class TestComputeDeltas:
    """compute_deltas — por campo de DELTA_CAMPOS; null quando nao ha base ou medida."""

    def test_variacao_por_campo(self):
        current = {"spend_brl": 1200.0, "purchases": 40}
        previous = {"spend_brl": 1000.0, "purchases": 30}
        deltas = compute_deltas(current, previous)
        assert deltas["spend_brl_pct"] == 20.0
        assert deltas["purchases_pct"] == 33.33

    def test_anterior_zero_da_null(self):
        deltas = compute_deltas({"spend_brl": 100.0}, {"spend_brl": 0.0})
        assert deltas["spend_brl_pct"] is None

    def test_lado_nao_medido_da_null_nao_menos_cem(self):
        """Antes, campo ausente contava como 0 e a variacao saia -100%."""
        deltas = compute_deltas({"purchases": None}, {"purchases": 10})
        assert deltas["purchases_pct"] is None
        deltas = compute_deltas({}, {"leads": 10})
        assert deltas["leads_pct"] is None

    def test_iguais_dao_zero_nao_null(self):
        deltas = compute_deltas({"spend_brl": 500.0}, {"spend_brl": 500.0})
        assert deltas["spend_brl_pct"] == 0.0

    def test_chaves_sao_as_de_delta_campos(self):
        from src.meta_ads.account_overview import DELTA_CAMPOS

        deltas = compute_deltas({}, {})
        assert set(deltas) == {f"{c}_pct" for c in DELTA_CAMPOS}
        assert "messaging_conversations_started_pct" in deltas


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
