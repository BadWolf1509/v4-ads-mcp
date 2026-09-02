"""GAQL das TRES camadas de vinculo de asset (F134/F135).

Precedencia NAO e calculada: a probe de 2026-09-02 (spec secao 5.1) mostrou que o
conceito nao existe na API — `AssetLinkPrimaryStatusReason` tem seis valores e
nenhum e de precedencia, e dois vinculos coexistentes do mesmo asset voltam ambos
`ELIGIBLE`. O que se devolve e o veredito do proprio Google: `primary_status`.

Status NAO e filtrado: linha `REMOVED` e a unica prova positiva de remocao
(spec secao 7).
"""

from typing import Any

from src.google_ads.queries._gaql import gaql_escape

_CAMPOS_COMUNS = "field_type, status, primary_status, primary_status_reasons, resource_name"


def _clausula_field_type(recurso: str, field_type: str | None) -> str:
    if field_type is None:
        return ""
    return f" WHERE {recurso}.field_type = '{gaql_escape(field_type)}'"


def build_customer_asset_query(*, field_type: str | None) -> str:
    campos = ", ".join(f"customer_asset.{c}" for c in _CAMPOS_COMUNS.split(", "))
    return f"SELECT {campos}, asset.id, asset.name FROM customer_asset" + _clausula_field_type(
        "customer_asset", field_type
    )


def build_campaign_asset_query(*, field_type: str | None, campaign_ids: list[str] | None) -> str:
    campos = ", ".join(f"campaign_asset.{c}" for c in _CAMPOS_COMUNS.split(", "))
    q = f"SELECT {campos}, asset.id, asset.name, campaign.id, campaign.name FROM campaign_asset"
    filtros = []
    if field_type is not None:
        filtros.append(f"campaign_asset.field_type = '{gaql_escape(field_type)}'")
    if campaign_ids:
        # ids sao validados como digit-string no schema da tool
        filtros.append(f"campaign.id IN ({','.join(campaign_ids)})")
    return q + (" WHERE " + " AND ".join(filtros) if filtros else "")


def build_ad_group_asset_query(*, field_type: str | None) -> str:
    campos = ", ".join(f"ad_group_asset.{c}" for c in _CAMPOS_COMUNS.split(", "))
    return (
        f"SELECT {campos}, asset.id, asset.name, ad_group.id, ad_group.name, "
        "campaign.id, campaign.name FROM ad_group_asset"
    ) + _clausula_field_type("ad_group_asset", field_type)


def _nome(enum_ou_none: Any) -> str:
    return enum_ou_none.name if hasattr(enum_ou_none, "name") else str(enum_ou_none)


def _base(link: Any, asset: Any, level: str) -> dict[str, Any]:
    return {
        "level": level,
        "resource_name": str(link.resource_name),
        "asset_id": str(asset.id),
        "asset_name": str(asset.name),
        "field_type": _nome(link.field_type),
        "status": _nome(link.status),
        "primary_status": _nome(link.primary_status),
        "primary_status_reasons": [_nome(r) for r in link.primary_status_reasons],
        "campaign_id": None,
        "campaign_name": None,
        "ad_group_id": None,
        "ad_group_name": None,
    }


def parse_customer_asset_row(row: Any) -> dict[str, Any]:
    return _base(row.customer_asset, row.asset, "CUSTOMER")


def parse_campaign_asset_row(row: Any) -> dict[str, Any]:
    d = _base(row.campaign_asset, row.asset, "CAMPAIGN")
    d["campaign_id"] = str(row.campaign.id)
    d["campaign_name"] = str(row.campaign.name)
    return d


def parse_ad_group_asset_row(row: Any) -> dict[str, Any]:
    d = _base(row.ad_group_asset, row.asset, "AD_GROUP")
    d["campaign_id"] = str(row.campaign.id)
    d["campaign_name"] = str(row.campaign.name)
    d["ad_group_id"] = str(row.ad_group.id)
    d["ad_group_name"] = str(row.ad_group.name)
    return d
