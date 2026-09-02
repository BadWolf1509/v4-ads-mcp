"""Agregacao pura do inventario de vinculos de asset — zero SDK, zero I/O.

NAO calcula precedencia. A probe de 2026-09-02 (spec secao 5.1) mostrou que o
conceito nao existe na API. O que se reporta e o `primary_status` do Google.

"Orfao" aqui significa: nenhum vinculo com status ENABLED em NENHUMA das tres
camadas. A checagem tem de olhar as tres — foi exatamente olhar so uma que
produziu o erro de 02/09.
"""

from collections import Counter
from typing import Any

_ORDEM_CAMADA = {"CUSTOMER": 0, "CAMPAIGN": 1, "AD_GROUP": 2}


def build_inventory(
    *, rows: list[dict[str, Any]], limit: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Ordena, conta e marca orfaos. Devolve (links_truncados, summary)."""
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
    summary = {
        "total_links": total,
        "truncated": total > limit,
        "by_level": dict(by_level),
        "by_primary_status": dict(by_primary),
        "assets_sem_vinculo_ativo": sorted(a for a, vivo in tem_vinculo_vivo.items() if not vivo),
    }
    return ordenados[:limit], summary
