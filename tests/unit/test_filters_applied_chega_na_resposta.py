"""A resposta de cada tool traz em `filters_applied` o `filtros` EXATO da query que rodou.

A completude derivada (test_filters_applied_e_derivado.py) prova que a FUNCAO de
query sabe o recorte; esta prova que a TOOL o entrega, e que a query cujo recorte
ela declara e a mesma que ela mandou ao Google (spec 2026-09-25, §3.3).
"""

from __future__ import annotations

import copy
import importlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current

_CONTA = "1234567890"

Registro = dict[str, list[tuple[str, dict[str, Any]]]]

_FRASE_DO_ECO = "filters_applied diz o recorte que a query aplicou."


@pytest.fixture(autouse=True)
def _ctx() -> Iterator[None]:
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


@dataclass(frozen=True)
class Caso:
    tool: str
    funcoes: tuple[str, ...]  # nomes NO MODULO DA TOOL, espionados
    esperado: Callable[[Registro], Any]  # o filters_applied que a resposta tem de trazer
    args: dict[str, Any] = field(default_factory=dict)


def _unico(funcao: str) -> Callable[[Registro], Any]:
    return lambda r: r[funcao][0][1]


CASOS: list[Caso] = [
    Caso(
        "get_campaign_performance",
        ("campaign_performance_query",),
        _unico("campaign_performance_query"),
    ),
    Caso(
        "get_ad_group_performance",
        ("ad_group_performance_query",),
        _unico("ad_group_performance_query"),
    ),
    Caso(
        "get_keyword_performance",
        ("keyword_performance_query",),
        _unico("keyword_performance_query"),
    ),
    Caso("get_ad_performance", ("ad_performance_query",), _unico("ad_performance_query")),
    Caso(
        "get_audience_performance",
        ("audience_performance_query",),
        _unico("audience_performance_query"),
    ),
    Caso(
        "get_device_performance", ("device_performance_query",), _unico("device_performance_query")
    ),
    Caso("get_geo_performance", ("geo_performance_query",), _unico("geo_performance_query")),
    Caso(
        "get_hourly_performance", ("hourly_performance_query",), _unico("hourly_performance_query")
    ),
    Caso(
        "get_performance_breakdown",
        ("build_performance_breakdown_query",),
        _unico("build_performance_breakdown_query"),
        {"level": "campaign"},
    ),
]


def _janelas(resposta: dict[str, Any]) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """(o que `period`/`previous_period` dizem, o que os `date_range` ecoados dizem).

    A resposta ja trazia `period` (`{from, to}`); o eco repete a janela na forma
    do F191 (`{start, end}`). Dois lugares para o mesmo dado so nao divergem se
    algo confere — e e aqui.
    """
    ditas = {
        (resposta[k]["from"], resposta[k]["to"])
        for k in ("period", "previous_period")
        if k in resposta
    }
    fa = resposta["filters_applied"]
    blocos = [fa, *(v for v in fa.values() if isinstance(v, dict))]
    ecoadas = {
        (b["date_range"]["start"], b["date_range"]["end"])
        for b in blocos
        if isinstance(b.get("date_range"), dict) and "start" in b["date_range"]
    }
    return ditas, ecoadas


@pytest.mark.asyncio
@pytest.mark.parametrize("caso", CASOS, ids=[c.tool for c in CASOS])
async def test_a_resposta_ecoa_o_recorte_da_query_que_rodou(caso: Caso) -> None:
    from src.mcp.tools._registry import get_tool, import_all_tools

    import_all_tools()
    tool = get_tool(caso.tool)
    assert tool is not None, f"tool `{caso.tool}` nao esta no registry"
    modulo = importlib.import_module(f"src.mcp.tools.{caso.tool}")

    registro: Registro = {f: [] for f in caso.funcoes}
    espioes = []
    for nome in caso.funcoes:
        original = getattr(modulo, nome)

        def espiao(*a: Any, _o: Any = original, _n: str = nome, **k: Any) -> Any:
            resultado = _o(*a, **k)
            # F-round1 achado 2: guardar o MESMO objeto que a tool recebe deixa o
            # guard comparar o objeto consigo mesmo — se a tool mutasse `filtros`
            # no lugar antes de devolver, os dois lados mudariam juntos e o `==`
            # continuaria verdadeiro. `deepcopy` prende o valor no instante da
            # chamada, antes de qualquer mutacao posterior da tool.
            registro[_n].append(copy.deepcopy(resultado))
            return resultado

        espioes.append(patch.object(modulo, nome, side_effect=espiao))

    with patch.object(modulo, "run_report", new_callable=AsyncMock) as rr:
        rr.return_value = []
        for e in espioes:
            e.start()
        try:
            resposta = await tool.handler({"customer_id": _CONTA, **caso.args})
        finally:
            for e in espioes:
                e.stop()

    executadas = [c.kwargs["query"] for c in rr.await_args_list]
    for nome, chamadas in registro.items():
        assert chamadas, f"`{nome}` nao foi chamada — a tool nao usa a funcao que o caso diz"
        for gaql, _filtros in chamadas:
            assert gaql in executadas, f"a tool rodou outra query que a de `{nome}`"
    assert resposta["filters_applied"] == caso.esperado(registro)
    ditas, ecoadas = _janelas(resposta)
    assert ditas == ecoadas, f"`period` diz {ditas} e o eco diz {ecoadas}"
    assert _FRASE_DO_ECO in tool.description, (
        f"`{caso.tool}` ecoa filters_applied e a description nao diz (spec §3.2)"
    )
