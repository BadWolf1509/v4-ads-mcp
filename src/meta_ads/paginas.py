"""Paginas promoviveis de uma conta Meta (`/{act}/promote_pages`).

Leitura pura. Campos medidos na sonda de 2026-10-31. O Instagram vem de
`instagram_business_account.id` e, na falta dele, de `connected_instagram_account.id`;
`instagram_origem` diz qual dos dois respondeu. Ausente vira `None`, nunca string vazia.
"""

from __future__ import annotations

from typing import Any

from src.meta_ads.reports import run_meta_graph_get

_OPERACAO = "meta_get_pages"
_TAMANHO_MAX_PAGINA = 100
_CAMPOS = "id,name,instagram_business_account,connected_instagram_account"


def _id_de(no: Any) -> str | None:
    if not isinstance(no, dict):
        return None
    valor = no.get("id")
    return str(valor) if valor not in (None, "") else None


def parse_pagina(linha: dict[str, Any]) -> dict[str, Any]:
    """Uma linha de `promote_pages` -> registro."""
    instagram_id = _id_de(linha.get("instagram_business_account"))
    origem = "instagram_business_account" if instagram_id else None
    if instagram_id is None:
        instagram_id = _id_de(linha.get("connected_instagram_account"))
        origem = "connected_instagram_account" if instagram_id else None
    return {
        "page_id": linha.get("id"),
        "nome": linha.get("name") or None,
        "instagram_id": instagram_id,
        "instagram_origem": origem,
    }


def build_pages_call(ad_account_id: str, *, limit: int) -> tuple[str, dict[str, Any]]:
    """Edge e params. Pede uma linha a mais que `limit` para provar o truncamento."""
    return f"/{ad_account_id}/promote_pages", {
        "fields": _CAMPOS,
        "limit": min(limit + 1, _TAMANHO_MAX_PAGINA),
    }


async def listar_paginas(
    ctx: Any, ad_account_id: str, limit: int
) -> tuple[list[dict[str, Any]], bool]:
    """Le as paginas seguindo `paging.next`. Devolve `(registros, truncated)`."""
    edge, params = build_pages_call(ad_account_id, limit=limit)
    pagina = int(params["limit"])
    max_pages = -(-(limit + 1) // pagina)
    resp = await run_meta_graph_get(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        ad_account_id=ad_account_id,
        edge=edge,
        params=params,
        operation_name=_OPERACAO,
        estimated_calls=max_pages,
        max_pages=max_pages,
        audit_this_call=True,
        params_summary={"ad_account_id": ad_account_id},
    )
    linhas = resp.get("data") or []
    sobrou_next = bool((resp.get("paging") or {}).get("next"))
    truncated = len(linhas) > limit or sobrou_next
    return [parse_pagina(linha) for linha in linhas[:limit]], truncated
