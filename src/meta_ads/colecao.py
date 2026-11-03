"""Leitura paginada de uma edge de colecao da Graph, compartilhada pelos modulos Meta.

`ler_colecao` e so o miolo que se repetia: calcula `max_pages` a partir do `limit` pedido e
do tamanho de pagina que o chamador pos em `params["limit"]`, chama o executor gateado e
devolve as linhas cruas e se sobrou `paging.next`. O `parse_*` e a regra de `truncated`
continuam em cada modulo, porque diferem (busca de segmentacao nao tem lista completa;
historico filtra antes de cortar).

O executor entra por parametro (`leitor`) e nao por import neste arquivo: os modulos
chamadores e os testes resolvem `run_meta_graph_get` no proprio namespace, e o helper nao
constroi cliente HTTP nenhum (so `run_meta_graph_get` o faz).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol
from uuid import UUID


class ContextoMeta(Protocol):
    """O que a leitura Meta precisa do contexto da sessao MCP (somente leitura: o contexto e imutavel)."""

    @property
    def manager_id(self) -> UUID: ...

    @property
    def session_id(self) -> UUID: ...


LeitorGraph = Callable[..., Awaitable[dict[str, Any]]]


async def ler_colecao(
    ctx: ContextoMeta,
    *,
    leitor: LeitorGraph,
    ad_account_id: str,
    edge: str,
    params: dict[str, Any],
    operacao: str,
    limit: int,
    params_summary: dict[str, Any],
) -> tuple[list[dict[str, Any]], bool]:
    """Le a edge seguindo `paging.next`. Devolve `(linhas_cruas, sobrou_next)`.

    `max_pages` cobre `limit + 1` linhas no tamanho de pagina de `params["limit"]`; a pagina
    extra e a linha a mais que prova o truncamento.
    """
    max_pages = -(-(limit + 1) // int(params["limit"]))
    resp = await leitor(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        ad_account_id=ad_account_id,
        edge=edge,
        params=params,
        operation_name=operacao,
        estimated_calls=max_pages,
        max_pages=max_pages,
        audit_this_call=True,
        params_summary=params_summary,
    )
    linhas = resp.get("data") or []
    sobrou_next = bool((resp.get("paging") or {}).get("next"))
    return linhas, sobrou_next
