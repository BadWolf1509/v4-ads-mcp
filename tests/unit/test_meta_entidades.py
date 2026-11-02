"""meta_get_entities: montagem da chamada e leitura das linhas (puro, sem rede)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.meta_ads import entidades
from src.meta_ads.entidades import build_entities_call, parse_entity


def test_status_configurado_e_efetivo_vem_separados() -> None:
    linha = {"id": "1", "name": "C", "status": "ACTIVE", "effective_status": "ADSET_PAUSED"}
    r = parse_entity("campaign", linha)
    assert r["status"] == "ACTIVE" and r["effective_status"] == "ADSET_PAUSED"


def test_orcamento_em_centavos_vira_brl() -> None:
    assert (
        parse_entity("campaign", {"id": "1", "daily_budget": "15050"})["daily_budget_brl"] == 150.5
    )


def test_vitalicio_e_restante_seguem_a_mesma_regra() -> None:
    r = parse_entity(
        "campaign", {"id": "1", "lifetime_budget": "200000", "budget_remaining": "12345"}
    )
    assert r["lifetime_budget_brl"] == 2000.0
    assert r["budget_remaining_brl"] == 123.45


def test_zero_e_ausente_viram_null() -> None:
    r = parse_entity(
        "campaign",
        {"id": "1", "daily_budget": "0", "lifetime_budget": "0", "budget_remaining": "0"},
    )
    assert r["daily_budget_brl"] is None
    assert r["lifetime_budget_brl"] is None
    assert r["budget_remaining_brl"] is None
    sem = parse_entity("campaign", {"id": "1"})
    assert sem["daily_budget_brl"] is None and sem["budget_remaining_brl"] is None


def test_restante_zero_com_orcamento_proprio_e_zero_medido() -> None:
    vitalicio = parse_entity(
        "campaign", {"id": "1", "lifetime_budget": "200000", "budget_remaining": "0"}
    )
    assert vitalicio["budget_remaining_brl"] == 0.0
    diario = parse_entity("adset", {"id": "1", "daily_budget": "5000", "budget_remaining": "0"})
    assert diario["budget_remaining_brl"] == 0.0


def test_restante_zero_sem_orcamento_proprio_e_null() -> None:
    r = parse_entity("campaign", {"id": "1", "budget_remaining": "0"})
    assert r["budget_remaining_brl"] is None


def test_restante_ausente_com_orcamento_proprio_continua_null() -> None:
    r = parse_entity("campaign", {"id": "1", "lifetime_budget": "200000"})
    assert r["budget_remaining_brl"] is None


def test_orcamento_ilegivel_e_null() -> None:
    r = parse_entity("campaign", {"id": "1", "daily_budget": "abc", "budget_remaining": "1,5"})
    assert r["daily_budget_brl"] is None
    assert r["budget_remaining_brl"] is None


def test_conjunto_sem_orcamento_proprio_diz_a_origem() -> None:
    r = parse_entity("adset", {"id": "1", "campaign_id": "9"})
    assert r["daily_budget_brl"] is None and r["orcamento_em"] == "campanha"


def test_conjunto_com_zero_nos_dois_tambem_e_da_campanha() -> None:
    r = parse_entity("adset", {"id": "1", "daily_budget": "0", "lifetime_budget": "0"})
    assert r["orcamento_em"] == "campanha"


def test_conjunto_com_orcamento_proprio() -> None:
    assert parse_entity("adset", {"id": "1", "daily_budget": "5000"})["orcamento_em"] == "conjunto"
    assert (
        parse_entity("adset", {"id": "1", "lifetime_budget": "5000"})["orcamento_em"] == "conjunto"
    )


def test_campanha_e_anuncio_nao_tem_orcamento_em() -> None:
    assert "orcamento_em" not in parse_entity("campaign", {"id": "1"})
    assert "orcamento_em" not in parse_entity("ad", {"id": "1"})


def test_campo_ausente_e_null() -> None:
    r = parse_entity("ad", {"id": "1"})
    assert r["effective_status"] is None
    assert r["issues_info"] is None
    assert r["ad_review_feedback"] is None


def test_anuncio_extrai_o_id_do_criativo() -> None:
    r = parse_entity("ad", {"id": "1", "adset_id": "2", "creative": {"id": "77"}})
    assert r["creative_id"] == "77" and r["adset_id"] == "2"
    assert parse_entity("ad", {"id": "1"})["creative_id"] is None


def test_campos_estruturados_passam_como_vieram() -> None:
    info = [{"error_code": 1, "error_summary": "x"}]
    learn = {"status": "LEARNING"}
    r = parse_entity("adset", {"id": "1", "issues_info": info, "learning_stage_info": learn})
    assert r["issues_info"] == info and r["learning_stage_info"] == learn


@pytest.mark.parametrize(
    ("level", "edge"),
    [("campaign", "/act_1/campaigns"), ("adset", "/act_1/adsets"), ("ad", "/act_1/ads")],
)
def test_edge_por_nivel_contem_a_conta(level: str, edge: str) -> None:
    got, params = build_entities_call(level, "act_1", status=None, limit=100)  # type: ignore[arg-type]
    assert got == edge
    assert "filtering" not in params


def test_campos_pedidos_incluem_status_e_orcamento() -> None:
    _, p = build_entities_call("campaign", "act_1", status=None, limit=100)
    campos = p["fields"].split(",")
    for c in ("status", "effective_status", "configured_status", "daily_budget", "issues_info"):
        assert c in campos
    _, p = build_entities_call("ad", "act_1", status=None, limit=100)
    assert "creative{id}" in p["fields"] and "ad_review_feedback" in p["fields"]
    _, p = build_entities_call("adset", "act_1", status=None, limit=100)
    assert "learning_stage_info" in p["fields"]


def test_status_filtra_por_effective_status() -> None:
    _, p = build_entities_call("campaign", "act_1", status="PAUSED", limit=100)
    assert json.loads(p["filtering"]) == [
        {"field": "effective_status", "operator": "IN", "value": ["PAUSED"]}
    ]


@pytest.mark.asyncio
async def test_operacao_de_auditoria_e_a_do_chamador() -> None:
    g = AsyncMock(return_value={"data": []})
    ctx = SimpleNamespace(manager_id="m", session_id="s")
    with patch.object(entidades, "run_meta_graph_get", g):
        await entidades.listar_entidades(ctx, "act_1", "campaign", None, 10)
        assert g.await_args.kwargs["operation_name"] == "meta_get_entities"
        await entidades.listar_entidades(
            ctx, "act_1", "campaign", None, 10, operacao="meta_get_budget_pacing"
        )
        assert g.await_args.kwargs["operation_name"] == "meta_get_budget_pacing"


def test_limit_vira_tamanho_de_pagina_limitado() -> None:
    _, p = build_entities_call("campaign", "act_1", status=None, limit=500)
    assert p["limit"] == 100
    _, p = build_entities_call("campaign", "act_1", status=None, limit=10)
    assert p["limit"] == 11
