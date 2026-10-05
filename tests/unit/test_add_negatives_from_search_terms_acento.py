"""`add_negatives_from_search_terms`: acento (spec 2026-10-05, §3.3).

O que vai ao Google se confere pelo `payload` do `run_mutation`.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current

_MOD = "src.mcp.tools.add_negatives_from_search_terms"


@pytest.fixture(autouse=True)
def _ctx() -> Iterator[None]:
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


async def _chamar(negatives: list[dict[str, Any]], **extra: Any) -> tuple[dict[str, Any], Any]:
    from src.mcp.tools.add_negatives_from_search_terms import add_negatives_from_search_terms

    with patch(f"{_MOD}.run_mutation", new_callable=AsyncMock) as rm:
        rm.return_value = {"applied_count": 1, "provider_request_id": "r", "partial_failures": []}
        out = await add_negatives_from_search_terms(
            {"customer_id": "7862230676", "negatives": negatives, **extra}
        )
    return out, rm.await_args.kwargs["payload"]["negatives"]


def _n(termo: str, scope: str = "campaign", sid: str = "1", mt: str = "PHRASE") -> dict[str, str]:
    return {"search_term": termo, "match_type": mt, "scope": scope, "scope_id": sid}


@pytest.mark.parametrize("scope", ["campaign", "ad_group", "shared_set"])
async def test_acentuado_sem_par_e_avisado_em_todo_escopo(scope: str) -> None:
    out, lote = await _chamar([_n("material de construção", scope)])
    assert lote == [_n("material de construção", scope)]
    assert out["avisos"] == [
        {
            "tipo": "sem_variante_sem_acento",
            "search_term": "material de construção",
            "match_type": "PHRASE",
            "scope": scope,
            "scope_id": "1",
            "sugestao": "material de construcao",
        }
    ]


@pytest.mark.parametrize("scope", ["campaign", "ad_group", "shared_set"])
async def test_opt_in_grava_o_par_no_mesmo_escopo(scope: str) -> None:
    out, lote = await _chamar([_n("hidráulico", scope)], incluir_variante_sem_acento=True)
    assert lote == [_n("hidráulico", scope), _n("hidraulico", scope)]
    assert out["avisos"] == []
    variante = out["added"][1]
    assert variante["search_term"] == "hidraulico"
    assert variante["variante_de"] == "hidráulico"
    assert "variante_de" not in out["added"][0]


async def test_par_no_mesmo_pedido_e_escopo_nao_gera_aviso() -> None:
    out, lote = await _chamar(
        [_n("construção"), _n("construcao")], incluir_variante_sem_acento=True
    )
    assert out["avisos"] == []
    assert len(lote) == 2


async def test_par_em_outro_escopo_nao_conta() -> None:
    out, _ = await _chamar([_n("construção", sid="1"), _n("construcao", sid="2")])
    assert [a["scope_id"] for a in out["avisos"]] == ["1"]


async def test_o_payload_nao_leva_a_chave_interna() -> None:
    _, lote = await _chamar([_n("construção")], incluir_variante_sem_acento=True)
    assert all("variante_de" not in n for n in lote)


def test_description_e_schema() -> None:
    from src.mcp.tools._registry import get_tool, import_all_tools

    import_all_tools()
    t = get_tool("add_negatives_from_search_terms")
    assert t is not None
    for ancora in (
        "NAO aplica variante proxima em negativa",
        "incluir_variante_sem_acento",
        "variante_de",
        "so e conferido dentro do proprio pedido",
        "Plural e erro de digitacao NAO sao tratados",
    ):
        assert ancora in t.description, ancora
    assert "incluir_variante_sem_acento" in t.input_schema["properties"]
