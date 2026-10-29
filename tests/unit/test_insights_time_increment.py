"""`build_insights_call` aceita `time_increment` opcional (gasto diario do saldo da conta)."""

from datetime import date

from src.meta_ads.insights import build_insights_call


def test_sem_time_increment_a_chamada_e_a_de_antes():
    _, p = build_insights_call(
        level="account",
        ad_account_id="act_1",
        start=date(2026, 9, 1),
        end=date(2026, 9, 30),
        limit=100,
    )
    assert "time_increment" not in p
    assert p["sort"] == "spend_descending"
    assert p["use_unified_attribution_setting"] == "true"


def test_time_increment_vira_string():
    _, p = build_insights_call(
        level="account",
        ad_account_id="act_1",
        start=date(2026, 9, 1),
        end=date(2026, 9, 30),
        limit=100,
        time_increment=1,
    )
    assert p["time_increment"] == "1"
