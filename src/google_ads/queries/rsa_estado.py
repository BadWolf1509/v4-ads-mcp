"""GAQL do estado de revisao/politica de RSA (M1, spec 2026-11-14).

`FROM ad_group_ad` SEM `segments.date`: com segmento de data o anuncio recem-criado, que
nao teve impressao, some da leitura (mesma armadilha do N1). O estado e FOTO do instante:
logo apos o write o Google responde quase sempre "em revisao", entao isto nao e veredito.

Proto-plus omite campo default: "nao lido" e `None`, nunca o nome de um enum (F145).
Enum se compara por `.name`, nunca por presenca de atributo.
"""

from __future__ import annotations

import re
from typing import Any

_AD_ID = re.compile(r"^customers/\d+/(?:ads/(\d+)|adGroupAds/\d+~(\d+))$")


def ad_id_de_resource_name(resource_name: str) -> str:
    """`customers/{c}/ads/{id}` (AdService) ou `customers/{c}/adGroupAds/{ag}~{id}`."""
    m = _AD_ID.match(resource_name)
    if m is None:
        raise ValueError(f"resource_name de anuncio em formato desconhecido: {resource_name!r}")
    return m.group(1) or m.group(2)


def rsa_estado_query(ad_ids: list[str]) -> str:
    if len(ad_ids) == 0:
        raise ValueError("ad_ids vazio: ao menos um ad_id e obrigatorio")
    # `str(int(...))` e a defesa (F87): o builder e publico, o schema nao protege.
    ids = ",".join(str(int(a)) for a in ad_ids)
    return (
        "SELECT ad_group_ad.ad.id, ad_group_ad.policy_summary.approval_status, "
        "ad_group_ad.policy_summary.review_status, "
        "ad_group_ad.policy_summary.policy_topic_entries, "
        "ad_group_ad.ad.responsive_search_ad.headlines, "
        "ad_group_ad.ad.responsive_search_ad.descriptions "
        f"FROM ad_group_ad WHERE ad_group_ad.ad.id IN ({ids})"
    )


def _enum_ou_none(obj: Any, campo: str) -> str | None:
    """Nome do enum, ou `None` se o campo nao veio (default omitido) ou e UNSPECIFIED."""
    valor = getattr(obj, campo, None)
    nome = getattr(valor, "name", None)
    if nome is None and isinstance(valor, str):
        nome = valor
    if nome is None or nome in ("UNSPECIFIED", "UNKNOWN"):
        return None
    return str(nome)


def pinos_do_rsa(rsa: Any) -> dict[str, list[str]] | None:
    """`{posicao: [textos]}` dos assets pinados, ou `None` quando os assets nao vieram.

    RSA tem sempre >= 3 headlines: lista vazia e campo NAO LIDO (fora do SELECT, linha
    parcial), nunca "sem pino" — devolver `{}` ai afirmaria zero sem medir (F145).
    Asset sem pino vem com `pinned_field` UNSPECIFIED (ou sem o campo): nao conta.
    """
    headlines = list(getattr(rsa, "headlines", None) or [])
    if not headlines:
        return None
    pinos: dict[str, list[str]] = {}
    for a in headlines + list(getattr(rsa, "descriptions", None) or []):
        pino = _enum_ou_none(a, "pinned_field")
        if pino is not None:
            pinos.setdefault(pino, []).append(str(a.text))
    return pinos


def parse_rsa_estado_row(row: Any) -> dict[str, Any]:
    aga = row.ad_group_ad
    ps = getattr(aga, "policy_summary", None)
    rsa = aga.ad.responsive_search_ad
    topicos = [
        str(getattr(t, "topic", ""))
        for t in (getattr(ps, "policy_topic_entries", None) or [])
        if getattr(t, "topic", "")
    ]
    reprovados: list[dict[str, Any]] = []
    for campo, assets in (
        ("headline", getattr(rsa, "headlines", None) or []),
        ("description", getattr(rsa, "descriptions", None) or []),
    ):
        for a in assets:
            aprov = _enum_ou_none(getattr(a, "policy_summary_info", None), "approval_status")
            if aprov == "DISAPPROVED":
                reprovados.append({"campo": campo, "texto": str(a.text), "approval_status": aprov})
    pinos = pinos_do_rsa(rsa)
    return {
        "ad_id": str(aga.ad.id),
        "approval_status": _enum_ou_none(ps, "approval_status"),
        "review_status": _enum_ou_none(ps, "review_status"),
        "topicos": topicos,
        "assets_reprovados": reprovados,
        # `pinos` segue dict (contrato do M1); `pinos_lidos` diz se ele foi MEDIDO (G2).
        "pinos": pinos or {},
        "pinos_lidos": pinos is not None,
    }
