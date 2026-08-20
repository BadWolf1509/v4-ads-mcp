"""Paginação da Graph API — o único lugar que sabe seguir `paging.next`.

Existe porque a lógica nasceu dentro de `src/auth/meta_oauth.py` e passou a ser
reusada por quem não tem nada a ver com OAuth (o resync). Duplicar paginação é
o tipo de cópia que apodrece: a correção entra numa das duas e a outra fica.
"""

from typing import Any, NamedTuple

import httpx
import structlog

log = structlog.get_logger(__name__)


class PagedFetch(NamedTuple):
    """`complete=False` significa leitura TRUNCADA — página falhou ou cap estourou.

    Quem faz detecção destrutiva PRECISA olhar esta flag (F93): sobre lista
    truncada, "ausente" significa "página que não veio", não churn.
    """

    rows: list[dict[str, Any]]
    complete: bool


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
    proxima: str | None = url
    primeira = True
    for _ in range(max_pages):
        # mypy nao carrega o narrowing do `if not proxima` (linha ~53) atraves da
        # volta do loop — a entrada aqui e o join de "antes do for" (proxima=url,
        # sempre str) com "fim da iteracao anterior" (so reentra se proxima era
        # truthy). O assert documenta o invariante e restaura o narrowing.
        assert proxima is not None
        resp = await http.get(proxima, params=params if primeira else None, headers=headers)
        primeira = False
        if resp.status_code != 200:
            log.warning(
                "meta_graph_page_failed",
                status=resp.status_code,
                body=resp.text[:200],
                fetched_so_far=len(rows),
            )
            return PagedFetch(rows, False)
        body = resp.json()
        rows.extend(body.get("data", []))
        proxima = (body.get("paging") or {}).get("next")
        if not proxima:
            return PagedFetch(rows, True)
    log.warning("meta_graph_page_cap", fetched=len(rows))
    return PagedFetch(rows, False)
