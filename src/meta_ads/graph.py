"""Paginação da Graph API — o único lugar que sabe seguir `paging.next`.

Existe porque a lógica nasceu dentro do OAuth pessoal da Meta (removido em
11/2026) e passou a ser reusada por quem não tem nada a ver com OAuth (o resync). Duplicar paginação é
o tipo de cópia que apodrece: a correção entra numa das duas e a outra fica.
"""

from collections.abc import AsyncIterator
from typing import Any, NamedTuple

import httpx
import structlog

log = structlog.get_logger(__name__)

# Textos de `x-ad-api-version-warning` ja alarmados neste processo. `log.error`
# aciona a policy `severity>=ERROR`: sem deduplicar, cada resposta de cada
# chamada abriria um incidente. Um aviso por texto distinto por processo basta.
_avisos_vistos: set[str] = set()


def avisar_versao_meta(headers: httpx.Headers) -> None:
    """Alarma (ERROR, uma vez por texto) quando a Meta avisa sobre a versao do Graph.

    O header real, medido, e `x-ad-api-version-warning` (ex.: auto-upgrade de uma
    versao expirada). Ausente e o caso normal e nao faz nada.
    """
    aviso = headers.get("x-ad-api-version-warning")
    if not aviso or aviso in _avisos_vistos:
        return
    _avisos_vistos.add(aviso)
    log.error("meta_api_version_warning", aviso=aviso)


class PagedFetch(NamedTuple):
    """`complete=False` significa leitura TRUNCADA — página falhou ou cap estourou.

    Quem faz detecção destrutiva PRECISA olhar esta flag (F93): sobre lista
    truncada, "ausente" significa "página que não veio", não churn.
    """

    rows: list[dict[str, Any]]
    complete: bool


class CorpoIlegivel(NamedTuple):
    """Corpo de um 200 que não decodifica como JSON (`erro` é a exceção original).

    Entregue no lugar do corpo para que o consumidor capture os headers da página
    ANTES de decidir; o consumidor re-levanta `erro` (comportamento de sempre).
    """

    erro: ValueError


async def paginas_graph(
    http: httpx.AsyncClient,
    url: str,
    params: dict[str, Any],
    headers: dict[str, str],
    max_pages: int,
) -> AsyncIterator[tuple[httpx.Response, Any]]:
    """O laço único de `paging.next`: entrega cada `(resposta, corpo)`, sem decidir sobre ela.

    RECEBE o cliente, nunca o constrói (o executor é o único construtor, já
    gateado). Cada resposta passa pelo alarme de versão antes de sair. O corpo
    é decodificado UMA vez, aqui: em 200 vem o JSON (qualquer tipo — o gerador
    não decide o que fazer com corpo que não é objeto, só para de paginar);
    fora de 200 vem `None`, sem tentar decodificar; 200 que não decodifica vem
    como `CorpoIlegivel` (a exceção NÃO sai do gerador, senão a página perderia
    os headers do BUC) e encerra a iteração. O chamador decide o que
    fazer: parar (`break`/`raise`/`return`) fecha o gerador; se seguir, o
    gerador pede a próxima. Resposta não-200 ou sem objeto JSON encerra a
    iteração depois de entregue.

    `params` vai só na primeira chamada: a URL de `paging.next` já carrega
    cursor e fields. `headers` (Authorization) vai em CADA página (F82). A URL
    do `next` segue como STRING (F189).
    """
    proxima: str | None = None
    for _ in range(max_pages):
        if proxima is None:
            resp = await http.get(url, params=params, headers=headers)
        else:
            resp = await http.get(proxima, headers=headers)
        avisar_versao_meta(resp.headers)
        if resp.status_code != 200:
            yield resp, None
            return
        try:
            bruto = resp.json()
        except ValueError as erro:
            yield resp, CorpoIlegivel(erro)
            return
        yield resp, bruto
        if not isinstance(bruto, dict):
            return
        proxima = (bruto.get("paging") or {}).get("next")
        if not proxima:
            return


async def fetch_paginated(
    http: httpx.AsyncClient,
    url: str,
    *,
    access_token: str,
    params: dict[str, Any],
    max_pages: int = 50,
) -> PagedFetch:
    rows: list[dict[str, Any]] = []
    # F82 — token no HEADER, nunca na query: quem lê a URL num log contorna tudo.
    headers = {"Authorization": f"Bearer {access_token}"}
    lidas = 0
    async for resp, body in paginas_graph(http, url, params, headers, max_pages):
        lidas += 1
        if resp.status_code != 200:
            log.warning(
                "meta_graph_page_failed",
                status=resp.status_code,
                body=resp.text[:200],
                fetched_so_far=len(rows),
            )
            return PagedFetch(rows, False)
        if isinstance(body, CorpoIlegivel):
            raise body.erro
        if not isinstance(body, dict):
            # 200 sem objeto: leitura truncada, nao churn (F93). Guarda o que veio.
            log.warning(
                "meta_graph_body_nao_objeto",
                tipo=type(body).__name__,
                fetched_so_far=len(rows),
            )
            return PagedFetch(rows, False)
        rows.extend(body.get("data", []))
        if not (body.get("paging") or {}).get("next"):
            return PagedFetch(rows, True)
    log.warning("meta_graph_page_cap", fetched=len(rows), pages=lidas)
    return PagedFetch(rows, False)
