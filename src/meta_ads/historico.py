"""Historico de alteracoes de uma conta Meta (`/{act}/activities`).

Leitura pura. `since` e `until` (YYYY-MM-DD) sao obrigatorios em TODA chamada: sem eles,
ou com `time_range`, a Meta devolve vazio sem erro (sonda de 2026-10-31). Campo ausente
vira `None`, nunca string vazia.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from src.meta_ads.reports import run_meta_graph_get

_OPERACAO = "meta_get_change_history"
_TAMANHO_MAX_PAGINA = 100

# Campos medidos na sonda de 2026-10-31.
_CAMPOS = (
    "actor_id,actor_name,application_id,application_name,date_time_in_timezone,"
    "event_time,event_type,extra_data,object_id,object_name,object_type,translated_event_type"
)

# `object_type` de `activities` usa os nomes antigos da Graph.
_TIPOS_OBJETO: dict[str, str] = {
    "CAMPAIGN_GROUP": "campanha",
    "CAMPAIGN": "conjunto",
    "ADGROUP": "anuncio",
    "ACCOUNT": "conta",
}


def _detalhe(extra: Any) -> Any:
    """`extra_data` e JSON em string: decodifica; se falhar, devolve o texto como veio."""
    if extra is None or extra == "":
        return None
    if not isinstance(extra, str):
        return extra
    try:
        return json.loads(extra)
    except ValueError:
        return extra


def parse_atividade(linha: dict[str, Any]) -> dict[str, Any]:
    """Uma linha de `activities` -> registro. Consumido pelo drift da Onda 2."""
    tipo_objeto = linha.get("object_type")
    return {
        "ocorrido_em": linha.get("event_time"),
        "ator_id": linha.get("actor_id"),
        "ator_nome": linha.get("actor_name"),
        "tipo": linha.get("event_type"),
        "objeto_id": linha.get("object_id"),
        "objeto_tipo": _TIPOS_OBJETO.get(tipo_objeto, tipo_objeto)
        if isinstance(tipo_objeto, str)
        else None,
        "detalhe": _detalhe(linha.get("extra_data")),
    }


def build_activities_call(
    ad_account_id: str, *, since: date, until: date, limit: int
) -> tuple[str, dict[str, Any]]:
    """Edge e params. Pede uma linha a mais que `limit` para provar o truncamento."""
    return f"/{ad_account_id}/activities", {
        "fields": _CAMPOS,
        "since": since.isoformat(),
        "until": until.isoformat(),
        "limit": min(limit + 1, _TAMANHO_MAX_PAGINA),
    }


async def listar_atividades(
    ctx: Any, ad_account_id: str, since: date, until: date, limit: int
) -> tuple[list[dict[str, Any]], bool]:
    """Le as atividades seguindo `paging.next`. Devolve `(registros, truncated)`."""
    edge, params = build_activities_call(ad_account_id, since=since, until=until, limit=limit)
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
        params_summary={
            "ad_account_id": ad_account_id,
            "since": since.isoformat(),
            "until": until.isoformat(),
        },
    )
    linhas = resp.get("data") or []
    sobrou_next = bool((resp.get("paging") or {}).get("next"))
    truncated = len(linhas) > limit or sobrou_next
    return [parse_atividade(linha) for linha in linhas[:limit]], truncated
