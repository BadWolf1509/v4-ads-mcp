"""meta_get_pages: Instagram vinculado, lista vazia, paginacao e truncated."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current
from src.mcp.tools import meta_get_pages as modulo
from src.meta_ads import paginas
from src.meta_ads.errors import MetaAdsFriendlyError

_CONTA = "act_1"


@pytest.fixture(autouse=True)
def _ctx() -> Iterator[None]:
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _graph(resposta: Any) -> tuple[AsyncMock, Any]:
    g = AsyncMock(side_effect=resposta if isinstance(resposta, list) else [resposta])
    return g, patch.object(paginas, "run_meta_graph_get", g)


def _paginas(n: int) -> list[dict[str, Any]]:
    return [{"id": str(i), "name": f"Pagina {i}"} for i in range(n)]


def test_instagram_business_tem_precedencia() -> None:
    r = paginas.parse_pagina(
        {
            "id": "1",
            "name": "P",
            "instagram_business_account": {"id": "10"},
            "connected_instagram_account": {"id": "20"},
        }
    )
    assert r == {
        "page_id": "1",
        "nome": "P",
        "instagram_id": "10",
        "instagram_origem": "instagram_business_account",
    }


def test_cai_para_connected_quando_nao_ha_business() -> None:
    r = paginas.parse_pagina({"id": "1", "connected_instagram_account": {"id": "20"}})
    assert r["instagram_id"] == "20"
    assert r["instagram_origem"] == "connected_instagram_account"


def test_sem_instagram_e_null_nunca_vazio() -> None:
    for linha in (
        {"id": "1", "name": "P"},
        {"id": "1", "instagram_business_account": {}, "connected_instagram_account": None},
        {"id": "1", "instagram_business_account": {"id": ""}},
    ):
        r = paginas.parse_pagina(linha)
        assert r["instagram_id"] is None and r["instagram_origem"] is None


@pytest.mark.asyncio
async def test_pagina_sem_instagram_traz_null_na_tool() -> None:
    g, p = _graph({"data": [{"id": "1", "name": "P"}]})
    with p:
        r = await modulo.meta_get_pages({"ad_account_id": _CONTA})
    assert r["status"] == "success"
    assert r["pages"][0]["instagram_id"] is None


@pytest.mark.asyncio
async def test_lista_vazia_e_success() -> None:
    g, p = _graph({"data": []})
    with p:
        r = await modulo.meta_get_pages({"ad_account_id": _CONTA})
    assert r["status"] == "success" and r["pages"] == []
    assert r["total_returned"] == 0 and r["truncated"] is False


@pytest.mark.asyncio
async def test_edge_params_e_auditoria() -> None:
    g, p = _graph({"data": []})
    with p:
        await modulo.meta_get_pages({"ad_account_id": _CONTA})
    kw = g.await_args_list[0].kwargs
    assert kw["edge"] == "/act_1/promote_pages"
    assert kw["ad_account_id"] == "act_1"
    assert kw["operation_name"] == "meta_get_pages"
    assert kw["audit_this_call"] is True
    assert kw["params"]["fields"] == (
        "id,name,instagram_business_account,connected_instagram_account"
    )
    assert kw["params"]["limit"] == 100
    assert kw["max_pages"] == 2


@pytest.mark.asyncio
async def test_limite_menor_que_o_total_marca_truncated() -> None:
    g, p = _graph({"data": _paginas(6)})
    with p:
        r = await modulo.meta_get_pages({"ad_account_id": _CONTA, "limit": 5})
    assert r["truncated"] is True and len(r["pages"]) == 5 and r["truncated_hint"]
    assert g.await_args_list[0].kwargs["params"]["limit"] == 6


@pytest.mark.asyncio
async def test_limit_100_com_exatamente_100_linhas_nao_trunca() -> None:
    g, p = _graph({"data": _paginas(100)})
    with p:
        r = await modulo.meta_get_pages({"ad_account_id": _CONTA, "limit": 100})
    assert r["truncated"] is False and len(r["pages"]) == 100
    assert "truncated_hint" not in r


@pytest.mark.asyncio
async def test_paging_next_marca_truncated() -> None:
    g, p = _graph({"data": _paginas(5), "paging": {"next": "https://x"}})
    with p:
        r = await modulo.meta_get_pages({"ad_account_id": _CONTA, "limit": 5})
    assert r["truncated"] is True


@pytest.mark.asyncio
async def test_limite_alto_pede_varias_paginas() -> None:
    g, p = _graph({"data": _paginas(3)})
    with p:
        await modulo.meta_get_pages({"ad_account_id": _CONTA, "limit": 500})
    assert g.await_args_list[0].kwargs["max_pages"] == 6


@pytest.mark.asyncio
async def test_limit_fora_da_faixa_erra_sem_chamar_a_graph() -> None:
    g, p = _graph({"data": []})
    with p:
        r = await modulo.meta_get_pages({"ad_account_id": _CONTA, "limit": 501})
    assert r["status"] == "error"
    g.assert_not_awaited()


@pytest.mark.asyncio
async def test_erro_amigavel_da_graph_vira_envelope() -> None:
    g, p = _graph([MetaAdsFriendlyError("falhou", retryable=False)])
    with p:
        r = await modulo.meta_get_pages({"ad_account_id": _CONTA})
    assert r == {"status": "error", "error_message": "falhou"}
