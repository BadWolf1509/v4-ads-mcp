"""meta_get_entities: fluxo da tool (moeda, paginacao, truncated, erro)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current
from src.mcp.tools import meta_get_entities as modulo
from src.meta_ads import entidades

_CONTA = "act_1"


@pytest.fixture(autouse=True)
def _ctx() -> Iterator[None]:
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _patches(side_effect: Any) -> Any:
    g = AsyncMock(side_effect=side_effect)
    return (
        g,
        patch.object(modulo, "run_meta_graph_get", g),
        patch.object(entidades, "run_meta_graph_get", g),
    )


def _linhas(n: int) -> list[dict[str, Any]]:
    return [{"id": str(i), "name": f"C{i}", "status": "ACTIVE"} for i in range(n)]


@pytest.mark.asyncio
async def test_conta_sem_entidade_e_sucesso_com_lista_vazia() -> None:
    g, p1, p2 = _patches([{"currency": "BRL"}, {"data": []}])
    with p1, p2:
        r = await modulo.meta_get_entities({"ad_account_id": _CONTA, "level": "campaign"})
    assert r["status"] == "success"
    assert r["entities"] == [] and r["truncated"] is False


@pytest.mark.asyncio
async def test_envia_edge_e_params_certos_e_audita() -> None:
    g, p1, p2 = _patches([{"currency": "BRL"}, {"data": _linhas(1)}])
    with p1, p2:
        await modulo.meta_get_entities(
            {"ad_account_id": _CONTA, "level": "adset", "status": "PAUSED", "limit": 20}
        )
    moeda, lista = g.await_args_list[0].kwargs, g.await_args_list[1].kwargs
    assert moeda["edge"] == "/act_1"
    assert moeda["params"] == {"fields": "currency"}
    assert lista["edge"] == "/act_1/adsets"
    assert lista["ad_account_id"] == "act_1"
    assert lista["operation_name"] == "meta_get_entities"
    assert lista["audit_this_call"] is True
    assert lista["params"]["limit"] == 21
    assert json.loads(lista["params"]["filtering"])[0]["value"] == ["PAUSED"]
    assert lista["max_pages"] == 1


@pytest.mark.asyncio
async def test_limite_menor_que_o_total_marca_truncated() -> None:
    g, p1, p2 = _patches([{"currency": "BRL"}, {"data": _linhas(6)}])
    with p1, p2:
        r = await modulo.meta_get_entities(
            {"ad_account_id": _CONTA, "level": "campaign", "limit": 5}
        )
    assert r["truncated"] is True
    assert len(r["entities"]) == 5
    assert r["truncated_hint"]


@pytest.mark.asyncio
async def test_exatamente_o_limite_nao_e_truncado() -> None:
    g, p1, p2 = _patches([{"currency": "BRL"}, {"data": _linhas(5)}])
    with p1, p2:
        r = await modulo.meta_get_entities(
            {"ad_account_id": _CONTA, "level": "campaign", "limit": 5}
        )
    assert r["truncated"] is False and len(r["entities"]) == 5


@pytest.mark.asyncio
async def test_next_remanescente_sem_linha_extra_marca_truncated() -> None:
    g, p1, p2 = _patches(
        [{"currency": "BRL"}, {"data": _linhas(5), "paging": {"next": "https://x"}}]
    )
    with p1, p2:
        r = await modulo.meta_get_entities(
            {"ad_account_id": _CONTA, "level": "campaign", "limit": 5}
        )
    assert r["truncated"] is True


@pytest.mark.asyncio
async def test_limite_grande_segue_paginas_ate_o_necessario() -> None:
    g, p1, p2 = _patches([{"currency": "BRL"}, {"data": _linhas(3)}])
    with p1, p2:
        await modulo.meta_get_entities({"ad_account_id": _CONTA, "level": "ad", "limit": 500})
    assert g.await_args_list[1].kwargs["max_pages"] == 6
    assert g.await_args_list[1].kwargs["params"]["limit"] == 100


@pytest.mark.asyncio
async def test_moeda_diferente_de_brl_vira_erro_sem_listar() -> None:
    g, p1, p2 = _patches([{"currency": "USD"}, {"data": _linhas(2)}])
    with p1, p2:
        r = await modulo.meta_get_entities({"ad_account_id": _CONTA, "level": "campaign"})
    assert r["status"] == "error" and "BRL" in r["error_message"]
    assert g.await_count == 1


@pytest.mark.asyncio
async def test_erro_interno_do_executor_sobe_para_o_envelope_central() -> None:
    g, p1, p2 = _patches(RuntimeError("boom"))
    with p1, p2, pytest.raises(RuntimeError, match="boom"):
        await modulo.meta_get_entities({"ad_account_id": _CONTA, "level": "campaign"})


@pytest.mark.asyncio
async def test_payload_de_sucesso() -> None:
    linha = {
        "id": "9",
        "name": "Conj",
        "campaign_id": "3",
        "status": "ACTIVE",
        "effective_status": "CAMPAIGN_PAUSED",
        "daily_budget": "2500",
    }
    g, p1, p2 = _patches([{"currency": "BRL"}, {"data": [linha]}])
    with p1, p2:
        r = await modulo.meta_get_entities({"ad_account_id": _CONTA, "level": "adset"})
    assert r["level"] == "adset" and r["ad_account_id"] == _CONTA
    e = r["entities"][0]
    assert e["daily_budget_brl"] == 25.0 and e["orcamento_em"] == "conjunto"
    assert e["status"] == "ACTIVE" and e["effective_status"] == "CAMPAIGN_PAUSED"


def test_registrada_no_bucket_always() -> None:
    from src.mcp.tools._registry import get_tool, import_all_tools

    import_all_tools()
    t = get_tool("meta_get_entities")
    assert t is not None and t.bucket == "always"
    assert t.input_schema["properties"]["ad_account_id"]["pattern"] == r"^act_\d+$"


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, -1, 501])
async def test_limit_fora_da_faixa_erra_sem_chamar_a_graph(limit: int) -> None:
    g, p1, p2 = _patches([{"currency": "BRL"}, {"data": []}])
    with p1, p2:
        r = await modulo.meta_get_entities(
            {"ad_account_id": _CONTA, "level": "campaign", "limit": limit}
        )
    assert r["status"] == "error" and "entre 1 e 500" in r["error_message"]
    g.assert_not_awaited()
