"""As 9 tools da frente PR 4: cortam e DIZEM que cortaram.

Uma metade so nao basta: `truncated: true` com a lista inteira devolvida engana
igual, so na direcao oposta. Por isso cada caso afirma as DUAS — o campo e o
tamanho da lista — e existe o par simetrico (`nao_cortou`) que prende a
segunda mentira possivel, a do `truncated` que responde `true` sempre.

O guard estrutural (`test_declaracao_de_truncamento`) so ve que a chave
EXISTE em algum dict alcancavel; quem verifica que ela chega ao gestor com o
valor certo, por tool, e este arquivo.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current

_CONTA = "1234567890"


@pytest.fixture(autouse=True)
def _ctx() -> Iterator[None]:
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


# ---------------------------------------------------------------------------
# Linhas falsas. Cada tool so precisa das chaves que ela mesma toca depois do
# `run_report` — as demais atravessam intactas.
# ---------------------------------------------------------------------------


def _linha_simples(i: int) -> dict[str, Any]:
    return {"id": str(i), "cost_brl": float(i)}


def _linha_geo(i: int) -> dict[str, Any]:
    # `get_geo_performance` resolve o nome do pais depois do corte.
    return {"country_criterion_id": str(2000 + i), "cost_brl": float(i)}


def _linha_change(i: int) -> dict[str, Any]:
    # `campaign_id`/`ad_group_id` None de proposito: assim `_resolve_names`
    # nao dispara consulta nenhuma e o `run_report` mockado serve so a query
    # principal e a sonda de fronteira.
    return {
        "change_date_time": f"2026-09-0{(i % 9) + 1} 10:00:00",
        "user_email": "fulano@v4company.com",
        "client_type": "GOOGLE_ADS_WEB_CLIENT",
        "resource_type": "CAMPAIGN",
        "resource_id": str(i),
        "resource_name": "",
        "_resource_path": f"customers/{_CONTA}/campaigns/{i}",
        "operation": "UPDATE",
        "changed_fields": [],
        "campaign_id": None,
        "ad_group_id": None,
        "old_status": None,
        "new_status": None,
    }


# ---------------------------------------------------------------------------
# Arranjo por tool: como mockar a fonte de linhas e onde a lista sai.
# ---------------------------------------------------------------------------


@contextmanager
def _mock_run_report(modulo: str, linhas: list[dict[str, Any]]) -> Iterator[None]:
    with patch(f"src.mcp.tools.{modulo}.run_report", new_callable=AsyncMock) as m:
        m.return_value = linhas
        yield


@contextmanager
def _mock_geo(linhas: list[dict[str, Any]]) -> Iterator[None]:
    with ExitStack() as pilha:
        pilha.enter_context(_mock_run_report("get_geo_performance", linhas))
        pilha.enter_context(
            patch(
                "src.mcp.tools.get_geo_performance.lookup_country_names",
                new_callable=AsyncMock,
                return_value={},
            )
        )
        yield


@contextmanager
def _mock_audit_log(linhas: list[dict[str, Any]]) -> Iterator[None]:
    """`get_my_audit_log` nao passa por `run_report` — a fonte e o repositorio."""
    with ExitStack() as pilha:
        lista = pilha.enter_context(
            patch(
                "src.mcp.tools.get_my_audit_log.audit_log.list_for_manager",
                new_callable=AsyncMock,
                return_value=linhas,
            )
        )
        pilha.enter_context(
            patch("src.mcp.tools.get_my_audit_log.audit_log.record", new_callable=AsyncMock)
        )
        pool = pilha.enter_context(patch("src.mcp.tools.get_my_audit_log.connection.get_pool"))
        pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=None)
        pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        yield lista


# (nome, chave da lista na resposta, fabrica de linha, mock)
_TOOLS: list[tuple[str, str, Callable[[int], dict[str, Any]], Any]] = [
    ("get_campaign_performance", "rows", _linha_simples, None),
    ("get_ad_group_performance", "rows", _linha_simples, None),
    ("get_keyword_performance", "rows", _linha_simples, None),
    ("get_ad_performance", "rows", _linha_simples, None),
    ("get_audience_performance", "rows", _linha_simples, None),
    ("get_search_terms_report", "rows", _linha_simples, None),
    ("get_geo_performance", "rows", _linha_geo, _mock_geo),
    ("get_change_history", "rows", _linha_change, None),
    ("get_my_audit_log", "events", _linha_simples, _mock_audit_log),
]

_IDS = [t[0] for t in _TOOLS]


async def _chamar(nome: str, fabrica: Any, mock: Any, *, limite: int, quantas: int) -> Any:
    from src.mcp.tools._registry import get_tool, import_all_tools

    import_all_tools()
    tool = get_tool(nome)
    assert tool is not None, f"tool `{nome}` nao esta no registry"

    linhas = [fabrica(i) for i in range(quantas)]
    args: dict[str, Any] = {"limit": limite}
    if nome != "get_my_audit_log":  # unica sem `customer_id` obrigatorio
        args["customer_id"] = _CONTA

    contexto = mock(linhas) if mock is not None else _mock_run_report(nome, linhas)
    with contexto:
        return await tool.handler(args)


@pytest.mark.asyncio
@pytest.mark.parametrize(("nome", "chave", "fabrica", "mock"), _TOOLS, ids=_IDS)
async def test_tool_corta_no_teto_e_avisa(nome: str, chave: str, fabrica: Any, mock: Any) -> None:
    """Veio a linha sentinela (`limite + 1`): devolve `limite` linhas E avisa.

    As duas assercoes juntas de proposito. Só `truncated is True` passaria
    numa tool que declara e nao corta (a sentinela vaza pro gestor); só o
    tamanho passaria na que corta calada, que e o defeito original.
    """
    limite = 3
    fora = await _chamar(nome, fabrica, mock, limite=limite, quantas=limite + 1)

    assert fora["truncated"] is True, f"`{nome}` cortou e nao disse"
    assert len(fora[chave]) == limite, f"`{nome}` avisou do corte mas nao cortou"


@pytest.mark.asyncio
@pytest.mark.parametrize(("nome", "chave", "fabrica", "mock"), _TOOLS, ids=_IDS)
async def test_tool_nao_mente_quando_coube(nome: str, chave: str, fabrica: Any, mock: Any) -> None:
    """A mentira simetrica: `truncated` que responde `true` sempre e tao
    inutil quanto o que responde `false` sempre — o gestor perde a
    capacidade de distinguir "tem mais" de "acabou" nos dois casos.
    """
    limite = 3
    fora = await _chamar(nome, fabrica, mock, limite=limite, quantas=limite)

    assert fora["truncated"] is False, f"`{nome}` diz que cortou sem ter cortado"
    assert len(fora[chave]) == limite


@pytest.mark.asyncio
async def test_get_my_audit_log_pede_a_linha_sentinela_ao_repositorio() -> None:
    """A unica das 9 cujo teto nao passa por GAQL: o `+1` tem que ir no
    argumento do repositorio, senao `aplicar_limite` compara contra uma lista
    ja cortada em `limite` e o `truncated` morre igual — o guard da sentinela
    varre `queries/` e nao alcanca este caminho.
    """
    from src.mcp.tools._registry import get_tool, import_all_tools

    import_all_tools()
    tool = get_tool("get_my_audit_log")
    assert tool is not None

    with _mock_audit_log([]) as lista:
        await tool.handler({"limit": 42})

    assert lista.call_args.kwargs["limit"] == 43


@pytest.mark.asyncio
async def test_get_geo_performance_nao_resolve_o_pais_da_sentinela() -> None:
    """O corte vem ANTES do lookup de nomes: a linha sentinela nao pode
    custar uma consulta a mais nem entrar no conjunto de paises resolvidos.
    """
    linhas = [_linha_geo(i) for i in range(4)]
    with ExitStack() as pilha:
        pilha.enter_context(_mock_run_report("get_geo_performance", linhas))
        lookup = pilha.enter_context(
            patch(
                "src.mcp.tools.get_geo_performance.lookup_country_names",
                new_callable=AsyncMock,
                return_value={},
            )
        )
        from src.mcp.tools.get_geo_performance import get_geo_performance

        await get_geo_performance({"customer_id": _CONTA, "limit": 3})

    pedidos = lookup.call_args.kwargs["country_ids"]
    assert len(pedidos) == 3
    assert _linha_geo(3)["country_criterion_id"] not in pedidos


@pytest.mark.asyncio
async def test_get_change_history_conta_o_summary_sobre_as_linhas_cortadas() -> None:
    """`summary.total_changes` sai do MESMO conjunto que `rows`.

    Se o corte acontecesse depois da agregacao, o gestor leria um total que
    nao bate com a lista que recebeu — dois numeros para a mesma pergunta.
    """
    linhas = [_linha_change(i) for i in range(6)]
    with _mock_run_report("get_change_history", linhas):
        from src.mcp.tools.get_change_history import get_change_history

        fora = await get_change_history({"customer_id": _CONTA, "limit": 5})

    assert fora["truncated"] is True
    assert len(fora["rows"]) == 5
    assert fora["summary"]["total_changes"] == 5
