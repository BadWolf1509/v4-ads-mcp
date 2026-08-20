"""Fonte autoritativa: quais contas a parceria do BM da V4 nos dá.

Substitui `/me/adaccounts` como definidor do inventário. A diferença medida em
2026-08-20: a edge do BM devolveu 25 contas e `/me/adaccounts` 23 — porque esta
última só enxerga conta a que o system user foi atribuído INDIVIDUALMENTE.
Confundir as duas é o que tornava "saiu da parceria" indistinguível de "ninguém
atribuiu o SU" (F128).
"""

from typing import Any, NamedTuple

import httpx

from src.meta_ads.client import META_GRAPH_API_VERSION
from src.meta_ads.graph import fetch_paginated

_GRAPH = f"https://graph.facebook.com/{META_GRAPH_API_VERSION}"
# currency e timezone_name são OBRIGATÓRIOS aqui: `upsert_many` escreve
# `currency = EXCLUDED.currency`, então pedir menos campos do que a tabela
# guarda APAGA os que faltarem nas 24 contas. Verificado por probe em
# 2026-08-20 — as duas edges devolvem os dois campos quando pedidos.
_FIELDS = "id,name,account_status,business,currency,timezone_name"
_EDGES = ("client_ad_accounts", "owned_ad_accounts")


class PartnershipSnapshot(NamedTuple):
    accounts: list[dict[str, Any]]
    complete: bool


def to_account_payload(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Graph → dicts que `meta_ad_accounts.upsert_many` consome."""
    payload: list[dict[str, Any]] = []
    for a in rows:
        ad_id = a.get("id", "")
        if not ad_id.startswith("act_"):
            ad_id = f"act_{ad_id}"
        business = a.get("business") or {}
        payload.append(
            {
                "ad_account_id": ad_id,
                "business_id": business.get("id"),
                "business_name": business.get("name"),
                "account_name": a.get("name", ad_id),
                "currency": a.get("currency"),
                "timezone_name": a.get("timezone_name"),
                "account_status": a.get("account_status"),
            }
        )
    return payload


async def fetch_partnership(
    http: httpx.AsyncClient, *, access_token: str, business_id: str
) -> PartnershipSnapshot:
    """União das duas edges. Uma edge truncada contamina o snapshot inteiro.

    Contaminar é deliberado: com metade da lista não dá pra dizer que uma conta
    saiu da parceria, e é essa afirmação que revoga acesso.
    """
    linhas: list[dict[str, Any]] = []
    completo = True
    for edge in _EDGES:
        out = await fetch_paginated(
            http,
            f"{_GRAPH}/{business_id}/{edge}",
            access_token=access_token,
            params={"fields": _FIELDS, "limit": 200},
        )
        linhas.extend(out.rows)
        completo = completo and out.complete
    return PartnershipSnapshot(to_account_payload(linhas), completo)
