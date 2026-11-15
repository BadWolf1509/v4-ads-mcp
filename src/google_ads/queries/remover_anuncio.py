"""GAQL do remove_ad (S3, spec 2026-11-14): lookup dos anuncios e ENABLED por grupo.

Validadas contra a API (`validate_gaql`, MO-JP, 14/11): as duas queries passam.

Ids vao por `str(int())`: o schema ja restringe a `^[0-9]+$`, mas a query e publica
(o confirmador a monta a partir do payload persistido), entao a conversao e a defesa
contra injecao (F87) — levanta `ValueError` antes de qualquer escrita.

Proto-plus: `ad.type` vira `type_` (colide com builtin), enum se le por `.name` via
`nome_do_enum` (F145). Em proto-plus `system_managed_resource_source` existe SEMPRE: o
que separa a variacao (F181) do anuncio comum e o VALOR (`AD_VARIATIONS`), nunca a
presenca.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from src.google_ads.queries._common import nome_do_enum


def _nao_vazia(ids: Sequence[str]) -> Sequence[str]:
    if not ids:
        raise ValueError("lista de ids vazia: a GAQL nao aceita IN ()")
    return ids


def anuncios_query(ad_ids: Sequence[str]) -> str:
    return (
        "SELECT ad_group_ad.ad.id, ad_group_ad.ad.type, "
        "ad_group_ad.ad.system_managed_resource_source, ad_group_ad.status, "
        "ad_group.id, ad_group.name, campaign.name FROM ad_group_ad "
        f"WHERE ad_group_ad.ad.id IN ({', '.join(str(int(i)) for i in _nao_vazia(ad_ids))})"
    )


def _status_lido(valor: Any) -> str | None:
    nome = nome_do_enum(valor)
    return None if nome in ("UNSPECIFIED", "UNKNOWN") else nome


def parse_anuncio_row(row: Any) -> dict[str, Any]:
    aga = row.ad_group_ad
    return {
        "ad_id": str(aga.ad.id),
        "ad_type": nome_do_enum(aga.ad.type_),
        "system_managed_source": nome_do_enum(aga.ad.system_managed_resource_source),
        # UNSPECIFIED (campo omitido, default 0) e UNKNOWN (valor que o SDK nao conhece)
        # nao sao status medido: `None` = nao lido (F145), no preview e na releitura.
        "status": _status_lido(aga.status),
        "ad_group_id": str(row.ad_group.id),
        "ad_group_name": row.ad_group.name,
        "campaign_name": row.campaign.name,
    }


def enabled_por_grupo_query(ad_group_ids: Sequence[str]) -> str:
    # A contagem e feita na tool: a GAQL nao tem COUNT/GROUP BY.
    return (
        "SELECT ad_group.id, ad_group_ad.ad.id FROM ad_group_ad "
        f"WHERE ad_group.id IN ({', '.join(str(int(i)) for i in _nao_vazia(ad_group_ids))}) "
        "AND ad_group_ad.status = 'ENABLED'"
    )


def parse_enabled_row(row: Any) -> dict[str, str]:
    return {"ad_group_id": str(row.ad_group.id), "ad_id": str(row.ad_group_ad.ad.id)}
