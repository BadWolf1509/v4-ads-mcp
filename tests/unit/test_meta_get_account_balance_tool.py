"""meta_get_account_balance: fluxo das duas chamadas Graph, janela e auditoria."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current
from src.mcp.tools import meta_get_account_balance as modulo

_CONTA = "act_1"
_HOJE = date(2026, 10, 28)


@pytest.fixture(autouse=True)
def _ctx() -> Iterator[None]:
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _conta(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "Conta",
        "account_status": 1,
        "is_prepay_account": False,
        "spend_cap": "100000",
        "amount_spent": "40000",
        "balance": "0",
        "currency": "BRL",
    }
    return {**base, **kw}


def _patches(side_effect: Any) -> Any:
    g = AsyncMock(side_effect=side_effect)
    return (
        g,
        patch.object(modulo, "run_meta_graph_get", g),
        patch.object(modulo, "resolve_meta_account_today", AsyncMock(return_value=_HOJE)),
    )


@pytest.mark.asyncio
async def test_dias_sem_entrega_contam_como_zero() -> None:
    insights = {
        "data": [
            {"date_start": "2026-10-26", "spend": "30.00"},
            {"date_start": "2026-10-22", "spend": "40.00"},
        ]
    }
    g, p1, p2 = _patches([_conta(), insights])
    with p1, p2:
        resp = await modulo.meta_get_account_balance({"ad_account_id": _CONTA})
    assert resp["media_diaria_7d_brl"] == round(70 / 7, 2)


@pytest.mark.asyncio
async def test_insights_pede_time_increment() -> None:
    g, p1, p2 = _patches([_conta(), {"data": []}])
    with p1, p2:
        await modulo.meta_get_account_balance({"ad_account_id": _CONTA})
    params = g.await_args_list[1].kwargs["params"]
    assert params["time_increment"] == "1"
    assert params["use_unified_attribution_setting"] == "true"
    assert params["time_range"] == '{"since":"2026-09-28","until":"2026-10-27"}'


@pytest.mark.asyncio
async def test_edge_da_conta_e_a_conta_gateada() -> None:
    g, p1, p2 = _patches([_conta(), {"data": []}])
    with p1, p2:
        await modulo.meta_get_account_balance({"ad_account_id": _CONTA})
    primeira = g.await_args_list[0].kwargs
    assert primeira["edge"] == "/act_1"
    assert primeira["ad_account_id"] == "act_1"
    assert g.await_args_list[1].kwargs["ad_account_id"] == "act_1"


@pytest.mark.asyncio
async def test_as_duas_chamadas_auditam() -> None:
    g, p1, p2 = _patches([_conta(), {"data": []}])
    with p1, p2:
        await modulo.meta_get_account_balance({"ad_account_id": _CONTA})
    assert g.await_count == 2
    assert all(c.kwargs["audit_this_call"] is True for c in g.await_args_list)
    assert all(c.kwargs["operation_name"] == "meta_get_account_balance" for c in g.await_args_list)


@pytest.mark.asyncio
async def test_moeda_diferente_de_brl_vira_erro() -> None:
    g, p1, p2 = _patches([_conta(currency="USD"), {"data": []}])
    with p1, p2:
        resp = await modulo.meta_get_account_balance({"ad_account_id": _CONTA})
    assert resp["status"] == "error"
    assert "BRL" in resp["error_message"]


@pytest.mark.asyncio
async def test_erro_do_executor_vira_erro() -> None:
    g, p1, p2 = _patches(RuntimeError("boom"))
    with p1, p2:
        resp = await modulo.meta_get_account_balance({"ad_account_id": _CONTA})
    assert resp["status"] == "error"
    assert resp["error_message"]


@pytest.mark.parametrize("nome", ["get_account_balance", "meta_get_account_balance"])
def test_description_lista_as_seis_situacoes(nome: str) -> None:
    import re
    from typing import get_args

    from src.mcp.tools._registry import get_tool, import_all_tools
    from src.saldo import Situacao

    import_all_tools()
    tool = get_tool(nome)
    assert tool is not None
    for valor in get_args(Situacao):
        assert re.search(rf"(?<![\w]){valor}(?![\w])", tool.description), valor


@pytest.mark.asyncio
async def test_campo_ausente_na_resposta_vira_erro_claro() -> None:
    conta = _conta()
    del conta["spend_cap"]
    g, p1, p2 = _patches([conta, {"data": []}])
    with p1, p2:
        resp = await modulo.meta_get_account_balance({"ad_account_id": _CONTA})
    assert resp["status"] == "error"
    assert "spend_cap" in resp["error_message"]


@pytest.mark.asyncio
async def test_linha_de_insights_sem_date_start_vira_erro_claro() -> None:
    g, p1, p2 = _patches([_conta(), {"data": [{"spend": "5.00"}]}])
    with p1, p2:
        resp = await modulo.meta_get_account_balance({"ad_account_id": _CONTA})
    assert resp["status"] == "error"
    assert "date_start" in resp["error_message"]


@pytest.mark.asyncio
async def test_payload_de_sucesso_cantina() -> None:
    import json
    from pathlib import Path

    arq = Path(__file__).parents[2] / (
        ".superpowers/sdd/2026-10-29-saldo-da-conta/meta-sondagem-2026-10-28.jsonl"
    )
    cantina = json.loads(arq.read_text(encoding="utf-8").splitlines()[0])
    insights = {"data": [{"date_start": "2026-10-27", "spend": "10.00"}]}
    g, p1, p2 = _patches([cantina, insights])
    with p1, p2:
        resp = await modulo.meta_get_account_balance({"ad_account_id": "act_3709029949237406"})
    assert resp["status"] == "success"
    assert resp["aproximado"] is True
    assert resp["ad_account_id"] == "act_3709029949237406"
    assert resp["period"] == {"from": "2026-09-28", "to": "2026-10-27"}
    assert resp["trava_primeiro"] == "limite_de_gastos"
    assert resp["restante_brl"] == 556.49
    assert resp["situacao"] == "com_saldo"
