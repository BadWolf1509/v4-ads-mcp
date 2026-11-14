"""GAQL da assinatura de aplicacao automatica de recomendacao (N3, spec 2026-11-14).

A chave da assinatura e o TIPO: `customers/{cid}/recommendationSubscriptions/{TYPE}`.
Medido na MO-JP (14/11): 11 linhas, 4 delas com `type = UNKNOWN` e o MESMO
`resource_name` `.../UNKNOWN` (F185) — nao enderecaveis. Por isso `UNKNOWN` e
`UNSPECIFIED` ficam fora do universo assinavel.

Proto-plus: o campo e `type_` (sufixo por colidir com builtin) e enum se le por
`.name` (F145), via `nome_do_enum`.
"""

from __future__ import annotations

from typing import Any

from google.ads.googleads.v25.enums.types.recommendation_type import RecommendationTypeEnum

from src.google_ads.queries._common import nome_do_enum

# Derivado do enum do SDK no import, nao digitado: tipo novo do Google entra sozinho
# na proxima versao do SDK, e lista escrita a mao diverge (licao F142/F150).
TIPOS_ASSINAVEIS: tuple[str, ...] = tuple(
    nome
    for nome in RecommendationTypeEnum.RecommendationType.__members__
    if nome not in ("UNKNOWN", "UNSPECIFIED")
)

STATUS_ALVO: tuple[str, ...] = ("PAUSED", "ENABLED")


def resource_name_da_assinatura(customer_id: str, tipo: str) -> str:
    if tipo not in TIPOS_ASSINAVEIS:
        raise ValueError(f"tipo de recomendacao fora do universo assinavel: {tipo!r}")
    return f"customers/{customer_id}/recommendationSubscriptions/{tipo}"


def assinatura_query(tipo: str) -> str:
    # O tipo vai interpolado: a pertinencia ao enum e a defesa (F87) — o builder e
    # publico e o schema nao o protege.
    if tipo not in TIPOS_ASSINAVEIS:
        raise ValueError(f"tipo de recomendacao fora do universo assinavel: {tipo!r}")
    return (
        "SELECT recommendation_subscription.type, recommendation_subscription.status, "
        "recommendation_subscription.modify_date_time FROM recommendation_subscription "
        f"WHERE recommendation_subscription.type = '{tipo}'"
    )


def parse_assinatura_row(row: Any) -> dict[str, Any]:
    sub = row.recommendation_subscription
    return {
        "type": nome_do_enum(sub.type_),
        "status": nome_do_enum(sub.status),
        "modify_date_time": str(sub.modify_date_time) or None,
    }
