"""meta_get_change_history: janela, paginacao, truncated e erro."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current
from src.mcp.tools import meta_get_change_history as modulo
from src.meta_ads import historico

_CONTA = "act_1"
_HOJE = date(2026, 11, 1)


@pytest.fixture(autouse=True)
def _ctx() -> Iterator[None]:
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _patches(side_effect: Any) -> Any:
    g = AsyncMock(side_effect=side_effect)
    return (
        g,
        patch.object(historico, "run_meta_graph_get", g),
        patch.object(modulo, "resolve_meta_account_today", AsyncMock(return_value=_HOJE)),
    )


def _linhas(n: int) -> list[dict[str, Any]]:
    return [
        {
            "event_time": f"2026-11-01T00:{i % 60:02d}:00+0000",
            "event_type": "t",
            "object_id": str(i),
        }
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_padrao_sete_dias_e_declara_a_janela() -> None:
    g, p1, p2 = _patches([{"data": _linhas(2)}])
    with p1, p2:
        r = await modulo.meta_get_change_history({"ad_account_id": _CONTA})
    assert r["status"] == "success"
    assert r["date_range"] == {"start": "2026-10-26", "end": "2026-11-01", "days": 7}
    assert r["total_returned"] == 2 and r["truncated"] is False
    assert r["changes"][0]["tipo"] == "t"


@pytest.mark.asyncio
async def test_edge_params_since_until_e_auditoria() -> None:
    g, p1, p2 = _patches([{"data": []}])
    with p1, p2:
        await modulo.meta_get_change_history({"ad_account_id": _CONTA, "days": 30, "limit": 20})
    kw = g.await_args_list[0].kwargs
    assert kw["edge"] == "/act_1/activities"
    assert kw["ad_account_id"] == "act_1"
    assert kw["operation_name"] == "meta_get_change_history"
    assert kw["audit_this_call"] is True
    assert kw["params"]["since"] == "2026-10-03"
    assert kw["params"]["until"] == "2026-11-01"
    assert kw["params"]["limit"] == 21
    assert kw["max_pages"] == 1


@pytest.mark.asyncio
async def test_limite_menor_que_o_total_marca_truncated() -> None:
    g, p1, p2 = _patches([{"data": _linhas(6)}])
    with p1, p2:
        r = await modulo.meta_get_change_history({"ad_account_id": _CONTA, "limit": 5})
    assert r["truncated"] is True and len(r["changes"]) == 5
    assert r["truncated_hint"]


@pytest.mark.asyncio
async def test_paging_next_sem_linha_extra_marca_truncated() -> None:
    g, p1, p2 = _patches([{"data": _linhas(5), "paging": {"next": "https://x"}}])
    with p1, p2:
        r = await modulo.meta_get_change_history({"ad_account_id": _CONTA, "limit": 5})
    assert r["truncated"] is True


@pytest.mark.asyncio
async def test_exatamente_no_limite_nao_marca_truncated() -> None:
    g, p1, p2 = _patches([{"data": _linhas(5)}])
    with p1, p2:
        r = await modulo.meta_get_change_history({"ad_account_id": _CONTA, "limit": 5})
    assert r["truncated"] is False and "truncated_hint" not in r


@pytest.mark.asyncio
async def test_days_acima_de_30_e_recusado() -> None:
    g, p1, p2 = _patches([{"data": []}])
    with p1, p2:
        r = await modulo.meta_get_change_history({"ad_account_id": _CONTA, "days": 31})
    assert r["status"] == "error"
    g.assert_not_awaited()


@pytest.mark.asyncio
async def test_erro_da_graph_vira_erro_em_pt() -> None:
    g, p1, p2 = _patches(RuntimeError("boom"))
    with p1, p2:
        r = await modulo.meta_get_change_history({"ad_account_id": _CONTA})
    assert r["status"] == "error" and r["error_message"]


def test_registrada_como_defer_e_somente_leitura() -> None:
    from src.mcp.tools._registry import get_tool

    t = get_tool("meta_get_change_history")
    assert t is not None
    assert t.bucket == "defer"
    assert t.description.startswith("[DEFER]")
    assert t.input_schema["properties"]["ad_account_id"]["pattern"] == r"^act_\d+$"
