"""GAQL do ad_schedule. Superficie probada em 02/09 (validate_gaql) e 03/09 (run_gaql)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from src.google_ads.queries.ad_schedule import (
    ad_schedule_query,
    campaign_budget_query,
    campaigns_on_budgets_query,
    day_hour_metrics_query,
    parse_ad_schedule_row,
    parse_campaign_budget_row,
    parse_day_hour_row,
)


def test_ad_schedule_query_filtra_tipo_e_ordena_com_limit() -> None:
    q = ad_schedule_query(campaign_ids=["22169885957"], status="enabled", limit=200)
    assert "FROM campaign_criterion" in q
    assert "campaign_criterion.type = 'AD_SCHEDULE'" in q
    assert "campaign.id IN (22169885957)" in q
    assert "campaign_criterion.status = 'ENABLED'" in q
    assert "ORDER BY" in q and q.rstrip().endswith("LIMIT 201"), (
        "LIMIT = limit+1 (sentinela de truncamento, F98)"
    )
    for campo in ("day_of_week", "start_hour", "start_minute", "end_hour", "end_minute"):
        assert f"campaign_criterion.ad_schedule.{campo}" in q
    assert "campaign_criterion.bid_modifier" in q and "campaign_criterion.resource_name" in q


def test_ad_schedule_query_status_all_nao_filtra_status() -> None:
    q = ad_schedule_query(campaign_ids=None, status="all", limit=10)
    assert "campaign_criterion.status" not in q.split("WHERE", 1)[1]
    assert "campaign.id IN" not in q


def test_parse_ad_schedule_row_converte_minuto_enum_em_int() -> None:
    row = SimpleNamespace(
        campaign=SimpleNamespace(id=22169885957, name="CAB"),
        campaign_criterion=SimpleNamespace(
            criterion_id=348624223154,
            resource_name="customers/1/campaignCriteria/22169885957~348624223154",
            ad_schedule=SimpleNamespace(
                day_of_week=SimpleNamespace(name="MONDAY"),
                start_hour=7,
                end_hour=17,
                start_minute=SimpleNamespace(name="THIRTY"),
                end_minute=SimpleNamespace(name="UNSPECIFIED"),
            ),
            bid_modifier=1.2,
            status=SimpleNamespace(name="ENABLED"),
        ),
    )
    d = parse_ad_schedule_row(row)
    assert d["campaign_id"] == "22169885957" and d["criterion_id"] == "348624223154"
    assert (
        d["day_of_week"],
        d["start_hour"],
        d["start_minute"],
        d["end_hour"],
        d["end_minute"],
    ) == ("MONDAY", 7, 30, 17, 0)
    assert d["bid_modifier"] == 1.2 and d["status"] == "ENABLED"
    assert d["resource_name"].endswith("~348624223154")


def test_campaign_budget_query_traz_explicitly_shared_e_o_status_da_campanha() -> None:
    q = campaign_budget_query(campaign_ids=["1", "2"])
    assert "campaign_budget.explicitly_shared" in q and "campaign.campaign_budget" in q
    assert "campaign.id IN (1,2)" in q
    assert "campaign.status" in q, (
        "com ids a query NAO derruba REMOVED — sem o status a tool nao sabe se a "
        "campanha alvo esta removida ou pausada (F52/F90)"
    )


def test_campaign_budget_query_sem_ids_pega_todas_as_nao_removidas() -> None:
    """Ruling 1 (ledger): um builder so — sem ids, conta inteira menos REMOVED."""
    q = campaign_budget_query(campaign_ids=None)
    assert "campaign.id IN" not in q and "campaign.status != 'REMOVED'" in q


def test_parse_campaign_budget_row() -> None:
    row = SimpleNamespace(
        campaign=SimpleNamespace(
            id=1,
            name="A",
            campaign_budget="customers/1/campaignBudgets/77",
            status=SimpleNamespace(name="PAUSED"),
        ),
        campaign_budget=SimpleNamespace(id=77, explicitly_shared=True, amount_micros=310000000),
    )
    d = parse_campaign_budget_row(row)
    assert d == {
        "campaign_id": "1",
        "campaign_name": "A",
        "budget_resource_name": "customers/1/campaignBudgets/77",
        "budget_id": "77",
        "explicitly_shared": True,
        "amount_brl": 310.0,
        "status": "PAUSED",
    }


def test_campaigns_on_budgets_query_exclui_removidas_e_usa_literal_escapado() -> None:
    q = campaigns_on_budgets_query(budget_resource_names=["customers/1/campaignBudgets/77"])
    assert "campaign.campaign_budget IN ('customers/1/campaignBudgets/77')" in q
    assert "campaign.status != 'REMOVED'" in q


def test_day_hour_metrics_query_e_a_conjunta_probada_em_03_09() -> None:
    q = day_hour_metrics_query(
        campaign_ids=["21359547724"], start=date(2026, 8, 4), end=date(2026, 9, 2)
    )
    assert "FROM campaign" in q
    assert "segments.day_of_week" in q and "segments.hour" in q
    assert "metrics.cost_micros" in q and "metrics.conversions" in q
    assert "segments.date BETWEEN '2026-08-04' AND '2026-09-02'" in q
    assert "campaign.id IN (21359547724)" in q


def test_parse_day_hour_row_tipa_hora_e_custo() -> None:
    row = SimpleNamespace(
        campaign=SimpleNamespace(id=21359547724),
        segments=SimpleNamespace(day_of_week=SimpleNamespace(name="MONDAY"), hour=8),
        metrics=SimpleNamespace(cost_micros="314676351", conversions=13.998888),
    )
    d = parse_day_hour_row(row)
    assert d == {
        "campaign_id": "21359547724",
        "day_of_week": "MONDAY",
        "hour": 8,
        "cost_micros": 314676351,
        "conversions": 13.998888,
    }


@pytest.mark.parametrize(
    "builder",
    [
        lambda: ad_schedule_query(campaign_ids=[], status="enabled", limit=10),
        lambda: campaign_budget_query(campaign_ids=[]),
        lambda: day_hour_metrics_query(
            campaign_ids=[], start=date(2026, 8, 4), end=date(2026, 9, 2)
        ),
        lambda: campaigns_on_budgets_query(budget_resource_names=[]),
    ],
)
def test_lista_vazia_e_erro_alto_nunca_sem_filtro(builder) -> None:
    """Vazio que vira 'conta inteira' em silencio e a familia do F134. None = sem filtro; [] = bug do chamador."""
    with pytest.raises(ValueError, match="vazio"):
        builder()
