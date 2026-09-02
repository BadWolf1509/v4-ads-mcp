"""Agregacao pura do inventario de vinculos de asset — zero SDK, zero I/O.

NAO calcula precedencia. A probe de 2026-09-02 (spec secao 5.1) mostrou que o
conceito nao existe na API. O que se reporta e o `primary_status` do Google.

"Orfao" aqui significa: sem vinculo ENABLED em NENHUMA das tres camadas — o
que inclui asset cujo unico vinculo esta PAUSED ou so REMOVED (a spec falava
em "sem nenhum vinculo", que e outra coisa: um vinculo PAUSED e nenhum
vinculo dao veredito ENABLED-nenhuma-camada igual, mas so o primeiro tem
vinculo de fato). A checagem tem de olhar as tres camadas — foi exatamente
olhar so uma que produziu o erro de 02/09.
"""

from collections import Counter
from typing import Any

_ORDEM_CAMADA = {"CUSTOMER": 0, "CAMPAIGN": 1, "AD_GROUP": 2}


def build_inventory(
    *, rows: list[dict[str, Any]], limit: int, filter_active: bool
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Ordena, conta e marca orfaos. Devolve (links_truncados, summary).

    `filter_active` e obrigatorio (sem default) de proposito: um default
    silencioso "sem filtro" seria o mesmo erro de classe que este parametro
    existe pra evitar (F134, ao contrario). Quando `field_type` OU
    `campaign_ids` restringe a consulta, `rows` e um RECORTE parcial da conta
    — cada camada nao-filtrada continua completa, mas a filtrada nao — e
    calcular orfao sobre um recorte parcial pode produzir falso positivo: um
    asset cujo unico vinculo ENABLED cai fora do recorte aparenta nao ter
    vinculo nenhum. Um campo AUSENTE nao pode produzir um veredito falso; um
    campo presente-porem-errado pode. Por isso, com filtro ativo,
    `assets_sem_vinculo_ativo` NAO e emitido — em vez de sair errado, some, e
    `orphan_scope` explica o motivo. Reproducao medida: asset com vinculo
    REMOVED na campanha 111 e ENABLED na 222 dá lista vazia sem filtro (correto)
    e `['<asset_id>']` com `campaign_ids=['111']` (falso — o ENABLED da 222
    ficou fora da query, mas o vinculo existe e esta vivo).
    """
    ordenados = sorted(rows, key=lambda r: (r["asset_id"], _ORDEM_CAMADA.get(r["level"], 9)))

    by_level: Counter[str] = Counter()
    by_primary: Counter[str] = Counter()
    tem_vinculo_vivo: dict[str, bool] = {}
    for r in ordenados:
        by_level[r["level"]] += 1
        by_primary[r["primary_status"]] += 1
        vivo = r["status"] == "ENABLED"
        tem_vinculo_vivo[r["asset_id"]] = tem_vinculo_vivo.get(r["asset_id"], False) or vivo

    total = len(ordenados)
    summary: dict[str, Any] = {
        "total_links": total,
        "truncated": total > limit,
        "by_level": dict(by_level),
        "by_primary_status": dict(by_primary),
    }
    if filter_active:
        summary["orphan_scope"] = "nao_calculado_com_filtro"
    else:
        summary["assets_sem_vinculo_ativo"] = sorted(
            a for a, vivo in tem_vinculo_vivo.items() if not vivo
        )
        summary["orphan_scope"] = "conta_completa"
    return ordenados[:limit], summary
