"""Unit tests for BUC (X-Business-Use-Case-Usage) header parsing (Sprint M.2a Task 7).

Spec 2026-09-26 §5: "nao sei" e `None`, nunca `0`. Os quatro testes de vazio/
malformado/sem a conta afirmavam `== 0` — a regra que o spec revoga: o 0 era
indistinguivel de conta ociosa e sobrescrevia o ultimo valor medido.
"""

import json

from src.governance.rate_limit import _parse_buc_header_pct, _parse_insights_throttle


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


def test_parse_buc_returns_none_when_account_not_in_header():
    header = json.dumps(
        {"999": [{"type": "ads_read", "call_count": 50, "total_cputime": 0, "total_time": 0}]}
    )
    pct = _parse_buc_header_pct(header, ad_account_id="act_111")
    assert pct is None


def test_parse_buc_handles_empty_header():
    pct = _parse_buc_header_pct("", ad_account_id="act_123")
    assert pct is None


def test_parse_buc_handles_empty_json():
    pct = _parse_buc_header_pct("{}", ad_account_id="act_123")
    assert pct is None


def test_parse_buc_handles_malformed_json():
    pct = _parse_buc_header_pct("not valid json", ad_account_id="act_123")
    assert pct is None


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


def test_parse_buc_handles_none_header():
    assert _parse_buc_header_pct(None, ad_account_id="act_123") is None


def test_parse_buc_zero_medido_segue_zero():
    """Null e so para o que nao veio: 0% medido continua 0."""
    header = json.dumps({"123": [{"call_count": 0, "total_cputime": 0, "total_time": 0}]})
    assert _parse_buc_header_pct(header, ad_account_id="act_123") == 0


def test_parse_buc_entrada_sem_nenhum_campo_e_none():
    """Campo ausente nao e 0 medido: a entrada sem os tres nao diz nada."""
    header = json.dumps({"123": [{"type": "ads_insights", "estimated_time_to_regain_access": 0}]})
    assert _parse_buc_header_pct(header, ad_account_id="act_123") is None


def test_parse_buc_valor_nao_numerico_nao_conta_e_nao_levanta():
    """O int() levantava antes de o contador de chamadas gravar."""
    header = json.dumps({"123": [{"call_count": "x", "total_cputime": None, "total_time": 40}]})
    assert _parse_buc_header_pct(header, ad_account_id="act_123") == 40


# ============================================================================
# x-fb-ads-insights-throttle — onde vem a quota do APP em chamada /insights
# ============================================================================


def test_insights_throttle_forma_medida():
    """Forma medida em 26/09 (`scripts/probe_meta_metricas.py`)."""
    header = (
        '{"app_id_util_pct":0.02,"acc_id_util_pct":0,"ads_api_access_tier":"development_access"}'
    )
    assert _parse_insights_throttle(header) == {"app_id_util_pct": 0.02, "acc_id_util_pct": 0.0}


def test_insights_throttle_ausente_ou_malformado_e_none():
    assert _parse_insights_throttle(None) is None
    assert _parse_insights_throttle("") is None
    assert _parse_insights_throttle("nao json") is None
    assert _parse_insights_throttle("[1, 2]") is None
    assert _parse_insights_throttle('{"ads_api_access_tier": "x"}') is None


def test_insights_throttle_so_devolve_o_que_veio():
    assert _parse_insights_throttle('{"app_id_util_pct": 81}') == {"app_id_util_pct": 81.0}
