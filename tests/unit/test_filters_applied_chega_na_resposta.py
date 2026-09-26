"""A resposta de cada tool traz em `filters_applied` o `filtros` EXATO da query que rodou.

A completude derivada (test_filters_applied_e_derivado.py) prova que a FUNCAO de
query sabe o recorte; esta prova que a TOOL o entrega, e que a query cujo recorte
ela declara e a mesma que ela mandou ao Google (spec 2026-09-25, §3.3).
"""

from __future__ import annotations

import ast
import copy
import importlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current
from tests.unit import _guard_harness as h

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
    Caso("get_search_terms_report", ("search_terms_query",), _unico("search_terms_query")),
    Caso(
        "get_negative_keywords_audit",
        ("negative_keywords_audit_query",),
        _unico("negative_keywords_audit_query"),
    ),
    Caso(
        "get_conversion_actions", ("conversion_actions_query",), _unico("conversion_actions_query")
    ),
    Caso("get_funnel_metrics", ("funnel_query",), _unico("funnel_query")),
    Caso("get_budget_pacing", ("budget_pacing_query",), _unico("budget_pacing_query")),
    Caso(
        "get_top_keywords_creatives",
        ("top_keywords_query", "top_creatives_query"),
        lambda r: {
            "top_keywords": r["top_keywords_query"][0][1],
            "top_creatives": r["top_creatives_query"][0][1],
        },
    ),
    Caso(
        "get_account_overview",
        ("overview_query",),
        lambda r: {"current": r["overview_query"][0][1], "previous": r["overview_query"][1][1]},
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


# Modulos cujas funcoes montam o GAQL que as tools rodam. Tool que importa deles
# tem de estar em `CASOS`: a lista acima e conferida por varredura, nao lembrada.
_MODULOS_DE_QUERY = {
    "src.google_ads.queries.performance",
    "src.google_ads.queries.tactical",
    "src.google_ads.queries.client_report",
    "src.google_ads.queries.overview",
    "src.google_ads.queries.bulk_pause",
    "src.google_ads.performance_breakdown",
}
# O preview do bulk_pause_by_query e um dry-run de mutacao (grava token no banco):
# o eco dele e conferido em tests/unit/test_bulk_pause_tool.py.
_FORA_DO_ECO_DE_LEITURA = {"bulk_pause_by_query"}


def _tools_que_usam_as_funcoes_de_query() -> set[str]:
    return {
        p.stem
        for p in h.fontes_py(h.SRC / "mcp" / "tools")
        if any(
            isinstance(no, ast.ImportFrom) and no.module in _MODULOS_DE_QUERY
            for no in ast.walk(h.arvore(p))
        )
    }


def test_toda_tool_que_monta_query_dos_cinco_modulos_esta_no_eco() -> None:
    usam = _tools_que_usam_as_funcoes_de_query()
    assert len(usam) >= 17, f"piso medido em 26/09 (16 de leitura + bulk_pause): {sorted(usam)}"
    faltam = sorted(usam - _FORA_DO_ECO_DE_LEITURA - {c.tool for c in CASOS})
    assert not faltam, (
        f"tool que roda query dos cinco modulos e nao esta em CASOS: {faltam}. "
        "Acrescente o Caso: a resposta dela tem de ecoar filters_applied."
    )
