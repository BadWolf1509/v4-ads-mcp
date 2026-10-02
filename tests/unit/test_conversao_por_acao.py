"""Recorte por ação de conversão — consultas, parse e combinações (spec 2026-10-02, §3.1).

Fatos medidos em 02/10 (Mestre da Obra – João Pessoa): recortar por ação recusa métrica de
custo (sem CPA por ação); `conversions` por ação segue `include_in_conversions_metric`.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from src.google_ads.performance_breakdown import (
    _validate_combo,
    build_performance_breakdown_query,
    parse_performance_row,
)
from src.google_ads.queries.performance import (
    conversion_action_breakdown_query,
    conversion_action_flags_query,
)

_S, _E = date(2026, 9, 1), date(2026, 9, 30)


def test_conta_por_acao_sem_custo_ordenada_e_com_sentinela() -> None:
    gaql, filtros = conversion_action_breakdown_query("account", _S, _E, "enabled", 50)
    assert "FROM customer" in gaql
    for campo in (
        "segments.conversion_action",
        "segments.conversion_action_name",
        "segments.conversion_action_category",
        "metrics.conversions",
        "metrics.all_conversions",
        "metrics.conversions_value",
        "metrics.all_conversions_value",
    ):
        assert campo in gaql, campo
    assert "cost_micros" not in gaql  # a API recusa custo neste recorte
    assert "ORDER BY metrics.all_conversions DESC" in gaql
    assert "LIMIT 51" in gaql
    assert "campaign.status" not in gaql  # conta nao tem status de campanha
    assert filtros == {"date_range": {"start": "2026-09-01", "end": "2026-09-30"}}


def test_campanha_por_acao_traz_a_campanha_e_o_filtro_de_status() -> None:
    gaql, filtros = conversion_action_breakdown_query("campaign", _S, _E, "enabled", 10)
    assert "FROM campaign" in gaql
    assert "campaign.id" in gaql and "campaign.name" in gaql
    assert "campaign.status = 'ENABLED'" in gaql
    assert filtros["campaign_status"] == "ENABLED"
    gaql_all, filtros_all = conversion_action_breakdown_query("campaign", _S, _E, "all", 10)
    assert "campaign.status" not in gaql_all.split("WHERE")[1]
    assert "campaign_status" not in filtros_all


def test_recorte_por_acao_so_em_conta_e_campanha() -> None:
    with pytest.raises(ValueError):
        gaql, _ = conversion_action_breakdown_query("ad_group", _S, _E, "enabled", 10)


def test_flags_por_id_inteiro_com_teto_estrutural() -> None:
    gaql, filtros = conversion_action_flags_query(["6827189000", "6826176642"])
    assert "FROM conversion_action" in gaql
    assert "conversion_action.id IN (6827189000, 6826176642)" in gaql
    for campo in ("include_in_conversions_metric", "primary_for_goal", "status", "type"):
        assert f"conversion_action.{campo}" in gaql
    assert "LIMIT 1000" in gaql
    assert filtros == {"conversion_action_ids": ["6827189000", "6826176642"]}


@pytest.mark.parametrize("ids", [[], ["12", "3 OR 1=1"], [str(i) for i in range(1001)]])
def test_flags_recusa_lista_vazia_id_nao_numerico_ou_acima_do_teto(ids: list[str]) -> None:
    with pytest.raises(ValueError):
        gaql, _ = conversion_action_flags_query(ids)


def _linha(campanha: bool = False) -> SimpleNamespace:
    base = SimpleNamespace(
        segments=SimpleNamespace(
            conversion_action="customers/7862230676/conversionActions/6827189000",
            conversion_action_name="Whatsapp - JPA",
            conversion_action_category=SimpleNamespace(name="CONTACT"),
        ),
        metrics=SimpleNamespace(
            conversions=204.0,
            all_conversions=204.0,
            conversions_value=204.0,
            all_conversions_value=204.0,
        ),
    )
    if campanha:
        base.campaign = SimpleNamespace(id=21359547724, name="[GPC][JPA]")
    return base


def test_linha_por_acao_tem_formato_proprio_sem_custo() -> None:
    r = parse_performance_row(_linha(), "account", "conversion_action")
    assert r == {
        "conversion_action_id": "6827189000",
        "conversion_action_name": "Whatsapp - JPA",
        "categoria": "CONTACT",
        "conversions": 204.0,
        "all_conversions": 204.0,
        "conversions_value_brl": 204.0,
        "all_conversions_value_brl": 204.0,
    }


def test_linha_por_acao_na_campanha_traz_a_campanha() -> None:
    r = parse_performance_row(_linha(campanha=True), "campaign", "conversion_action")
    assert r["campaign_id"] == "21359547724"
    assert r["campaign_name"] == "[GPC][JPA]"
    assert "impressions" not in r and "cost_brl" not in r


def test_combinacoes_validas_e_invalidas() -> None:
    assert _validate_combo("account", "conversion_action") is None
    assert _validate_combo("campaign", "conversion_action") is None
    msg = _validate_combo("ad_group", "conversion_action")
    assert msg is not None and "conversion_action" in msg


def test_o_despachante_leva_o_recorte_ao_construtor_novo() -> None:
    gaql, _ = build_performance_breakdown_query(
        "campaign", "conversion_action", "enabled", _S, _E, 10
    )
    assert "segments.conversion_action" in gaql and "FROM campaign" in gaql
