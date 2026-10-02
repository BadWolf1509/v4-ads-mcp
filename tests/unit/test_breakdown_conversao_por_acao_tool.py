"""A tool `get_performance_breakdown` com `breakdown='conversion_action'` (spec 2026-10-02, §3.1).

As flags de cada ação vêm do recurso `conversion_action`, numa segunda consulta só com as
ações das linhas devolvidas. A que esse recurso não devolve — medido em 02/10: "Conversation
started" (`7028680990`), 173 conversões em setembro e zero linhas em `conversion_action` —
fica com flag `null` e motivo: ausência de medição não é `false` (F191).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current

_CONTA = "7862230676"


@pytest.fixture(autouse=True)
def _ctx() -> Iterator[None]:
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _acao(aid: str, nome: str, conv: float, todas: float) -> dict[str, Any]:
    return {
        "conversion_action_id": aid,
        "conversion_action_name": nome,
        "categoria": "CONTACT",
        "conversions": conv,
        "all_conversions": todas,
        "conversions_value_brl": conv,
        "all_conversions_value_brl": todas,
    }


def _flag(aid: str, conta: bool, primaria: bool) -> dict[str, Any]:
    return {
        "conversion_action_id": aid,
        "include_in_conversions_metric": conta,
        "primary_for_goal": primaria,
        "status": "ENABLED",
        "type": "WEBPAGE",
    }


async def _chamar(respostas: list[list[dict[str, Any]]], **args: Any) -> tuple[Any, AsyncMock]:
    from src.mcp.tools.get_performance_breakdown import get_performance_breakdown

    with (
        patch("src.mcp.tools.get_performance_breakdown.run_report", new_callable=AsyncMock) as rr,
        patch(
            "src.mcp.tools.get_performance_breakdown.resolve_account_today",
            new_callable=AsyncMock,
        ) as hoje,
    ):
        from datetime import date

        hoje.return_value = date(2026, 10, 2)
        rr.side_effect = respostas
        out = await get_performance_breakdown(
            {"customer_id": _CONTA, "level": "account", "breakdown": "conversion_action", **args}
        )
    return out, rr


_LINHAS = [
    _acao("6827189000", "Whatsapp - JPA", 204.0, 204.0),
    _acao("7028680990", "Conversation started", 173.0, 173.0),
    _acao("6826176642", "Clicks to call", 0.0, 11.0),
]


async def test_flags_vem_do_recurso_e_a_acao_ausente_fica_null_com_motivo() -> None:
    out, rr = await _chamar(
        [_LINHAS, [_flag("6827189000", True, True), _flag("6826176642", False, True)]]
    )
    por_id = {r["conversion_action_id"]: r for r in out["rows"]}
    assert por_id["6827189000"]["conta_em_conversoes"] is True
    assert por_id["6827189000"]["primary_for_goal"] is True
    assert por_id["6827189000"]["flags_motivo"] is None
    assert por_id["6826176642"]["conta_em_conversoes"] is False
    assert por_id["6826176642"]["primary_for_goal"] is True
    ausente = por_id["7028680990"]
    assert ausente["conta_em_conversoes"] is None
    assert ausente["primary_for_goal"] is None
    assert "conversion_action" in ausente["flags_motivo"]
    flags = rr.await_args_list[1].kwargs["query"]
    assert "conversion_action.id IN (6827189000, 7028680990, 6826176642)" in flags


async def test_corte_antes_das_flags_e_truncated() -> None:
    out, rr = await _chamar([_LINHAS, [_flag("6827189000", True, True)]], limit=2)
    assert out["truncated"] is True
    assert [r["conversion_action_id"] for r in out["rows"]] == ["6827189000", "7028680990"]
    # a sentinela (a 3a linha) nao entra na consulta das flags
    assert "6826176642" not in rr.await_args_list[1].kwargs["query"]


async def test_sem_linha_nao_roda_a_consulta_das_flags() -> None:
    out, rr = await _chamar([[]])
    assert out["rows"] == []
    assert rr.await_count == 1


async def test_filters_applied_e_period_do_recorte() -> None:
    out, rr = await _chamar([_LINHAS[:1], [_flag("6827189000", True, True)]])
    assert out["filters_applied"]["date_range"] == {"start": "2026-09-02", "end": "2026-10-01"}
    assert "FROM customer" in rr.await_args_list[0].kwargs["query"]


def test_description_diz_os_dois_contratos() -> None:
    from src.mcp.tools._registry import get_tool, import_all_tools

    import_all_tools()
    tool = get_tool("get_performance_breakdown")
    assert tool is not None
    d = tool.description
    assert "conversion_action" in d
    assert "conta_em_conversoes" in d and "all_conversions" in d
    assert "flags_motivo" in d
    assert "sem custo" in d.lower() or "nao ha custo" in d.lower()
    assert "parcela_impressao" in d
