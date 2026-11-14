"""GAQL dos experimentos e do comparativo base x variacao (G1, spec 2026-11-14).

Medido na MO-JP em 14/11 (v25):
- `FROM experiment` devolve id, nome, tipo (chave proto-plus `type_`), status e datas.
- `experiment_arm` volta so com `resource_name`/`experiment` (F181): a API NAO liga braco a
  anuncio, entao este modulo nunca o consulta.
- `ad_group_ad.ad.system_managed_resource_source = 'AD_VARIATIONS'` marca a variacao; no
  anuncio base o campo vem omitido (proto-plus le UNSPECIFIED). Compara-se pelo nome.

Data SO no WHERE (N1): `segments.date` no SELECT esconde o anuncio sem trafego na janela.
IDs interpolados passam por `str(int(...))` (F87): o builder e publico, o schema nao protege.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from src.google_ads.queries._common import gaql_date_clause, nome_do_enum

FONTE_VARIACAO = "AD_VARIATIONS"


def experimentos_query(experiment_id: str | None) -> str:
    base = (
        "SELECT experiment.experiment_id, experiment.name, experiment.type, "
        "experiment.status, experiment.start_date, experiment.end_date FROM experiment"
    )
    if experiment_id is None:
        return base
    return f"{base} WHERE experiment.experiment_id = {_id(experiment_id)}"


def anuncios_query() -> str:
    """RSAs ENABLED da conta, base e variacao — a separacao e feita no parser."""
    return (
        "SELECT ad_group.id, ad_group.name, campaign.name, ad_group_ad.ad.id, "
        "ad_group_ad.ad.system_managed_resource_source, ad_group_ad.ad.final_urls "
        "FROM ad_group_ad WHERE ad_group_ad.ad.type = 'RESPONSIVE_SEARCH_AD' "
        "AND ad_group_ad.status = 'ENABLED'"
    )


def metricas_query(ad_group_ids: list[str], *, start: date, end: date) -> str:
    if len(ad_group_ids) == 0:
        raise ValueError("ad_group_ids vazio: ao menos um grupo e obrigatorio")
    ids = ",".join(str(int(a)) for a in ad_group_ids)
    # Sem `segments.date` no SELECT: a linha vem agregada na janela e o anuncio sem
    # trafego simplesmente nao aparece (o chamador o conta como zero).
    return (
        "SELECT ad_group.id, ad_group_ad.ad.id, metrics.impressions, metrics.clicks, "
        "metrics.cost_micros, metrics.conversions FROM ad_group_ad "
        f"WHERE ad_group.id IN ({ids}) "
        "AND ad_group_ad.ad.type = 'RESPONSIVE_SEARCH_AD' "
        "AND ad_group_ad.status = 'ENABLED' "
        f"AND {gaql_date_clause(start, end)}"
    )


def _id(valor: str) -> str:
    try:
        return str(int(valor))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"id nao numerico: {valor!r}") from exc


def _data(valor: Any) -> str | None:
    texto = str(valor or "").strip()
    return texto[:10] if texto else None


def parse_experimento_row(row: Any) -> dict[str, Any]:
    e = row.experiment
    tipo = getattr(e, "type_", None)
    if tipo is None:
        tipo = getattr(e, "type", None)
    return {
        "experiment_id": str(e.experiment_id),
        "nome": str(e.name),
        "tipo": nome_do_enum(tipo),
        "status": nome_do_enum(e.status),
        "inicio": _data(e.start_date),
        "fim": _data(e.end_date),
    }


def parse_anuncio_row(row: Any) -> dict[str, Any]:
    ad = row.ad_group_ad.ad
    fonte = getattr(ad, "system_managed_resource_source", None)
    return {
        "ad_group_id": str(row.ad_group.id),
        "ad_group": str(row.ad_group.name),
        "campanha": str(row.campaign.name),
        "ad_id": str(ad.id),
        "variacao": fonte is not None and nome_do_enum(fonte) == FONTE_VARIACAO,
    }


def parse_metrica_row(row: Any) -> dict[str, Any]:
    m = row.metrics
    return {
        "ad_group_id": str(row.ad_group.id),
        "ad_id": str(row.ad_group_ad.ad.id),
        "impressions": int(m.impressions or 0),
        "clicks": int(m.clicks or 0),
        "cost_micros": int(m.cost_micros or 0),
        "conversions": float(m.conversions or 0.0),
    }
