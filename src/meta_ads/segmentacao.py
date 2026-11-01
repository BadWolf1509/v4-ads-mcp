"""Busca de segmentacao e estimativa de entrega de uma conta Meta.

Leitura pura. Edges medidas na sonda de 2026-10-31: `/{act}/targetingsearch` (sem `q` e 400)
e `/{act}/delivery_estimate` (so ela serve; `reachestimate` veio vazio). Campo ausente vira
`None`, nunca `0`. A estimativa e aproximada por natureza e sempre declara isso.
"""

from __future__ import annotations

import json
from typing import Any

from src.meta_ads.reports import run_meta_graph_get

_OP_BUSCA = "meta_search_targeting"
_OP_ESTIMATIVA = "meta_get_delivery_estimate"
_TAMANHO_MAX_PAGINA = 100

_CAMPOS_BUSCA = "id,name,type,path,audience_size_lower_bound,audience_size_upper_bound,description"


def _inteiro(valor: Any) -> int | None:
    """Inteiro da Meta (pode vir como string); ausente ou invalido vira None, nao 0."""
    if isinstance(valor, bool) or valor is None:
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def parse_interesse(linha: dict[str, Any]) -> dict[str, Any]:
    """Uma linha de `targetingsearch` -> registro, com a faixa de alcance em limites separados."""
    caminho = linha.get("path")
    return {
        "id": linha.get("id"),
        "nome": linha.get("name"),
        "tipo": linha.get("type"),
        "caminho": caminho if isinstance(caminho, list) else None,
        "audiencia_minima": _inteiro(linha.get("audience_size_lower_bound")),
        "audiencia_maxima": _inteiro(linha.get("audience_size_upper_bound")),
        "descricao": linha.get("description") or None,
    }


def build_search_call(ad_account_id: str, *, q: str, limit: int) -> tuple[str, dict[str, Any]]:
    """Edge e params. Pede uma linha a mais que `limit` para provar o truncamento."""
    return f"/{ad_account_id}/targetingsearch", {
        "q": q,
        "fields": _CAMPOS_BUSCA,
        "limit": min(limit + 1, _TAMANHO_MAX_PAGINA),
    }


async def buscar_segmentacao(
    ctx: Any, ad_account_id: str, q: str, limit: int
) -> tuple[list[dict[str, Any]], bool]:
    """Busca por texto. A API pode ignorar `limit`: corta aqui e declara `truncated`."""
    edge, params = build_search_call(ad_account_id, q=q, limit=limit)
    resp = await run_meta_graph_get(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        ad_account_id=ad_account_id,
        edge=edge,
        params=params,
        operation_name=_OP_BUSCA,
        estimated_calls=1,
        max_pages=1,
        audit_this_call=True,
        params_summary={"ad_account_id": ad_account_id, "q": q},
    )
    linhas = resp.get("data") or []
    sobrou_next = bool((resp.get("paging") or {}).get("next"))
    truncated = len(linhas) > limit or sobrou_next
    return [parse_interesse(linha) for linha in linhas[:limit]], truncated


def build_estimate_call(
    ad_account_id: str, *, targeting_spec: dict[str, Any], optimization_goal: str
) -> tuple[str, dict[str, Any]]:
    return f"/{ad_account_id}/delivery_estimate", {
        "targeting_spec": json.dumps(targeting_spec, ensure_ascii=False),
        "optimization_goal": optimization_goal,
    }


def parse_estimativa(linha: dict[str, Any]) -> dict[str, Any]:
    """Uma linha de `delivery_estimate`. A curva `daily_outcomes_curve` nao e devolvida."""
    pronta = linha.get("estimate_ready")
    return {
        "alcance_mensal_minimo": _inteiro(linha.get("estimate_mau_lower_bound")),
        "alcance_mensal_maximo": _inteiro(linha.get("estimate_mau_upper_bound")),
        "alcance_diario": _inteiro(linha.get("estimate_dau")),
        "estimativa_pronta": pronta if isinstance(pronta, bool) else None,
    }


async def estimar_entrega(
    ctx: Any, ad_account_id: str, targeting_spec: dict[str, Any], optimization_goal: str
) -> dict[str, Any] | None:
    """Estimativa de entrega, ou `None` quando a Meta devolve `data` vazio."""
    edge, params = build_estimate_call(
        ad_account_id, targeting_spec=targeting_spec, optimization_goal=optimization_goal
    )
    resp = await run_meta_graph_get(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        ad_account_id=ad_account_id,
        edge=edge,
        params=params,
        operation_name=_OP_ESTIMATIVA,
        estimated_calls=1,
        max_pages=1,
        audit_this_call=True,
        params_summary={
            "ad_account_id": ad_account_id,
            "optimization_goal": optimization_goal,
        },
    )
    linhas = resp.get("data") or []
    if not linhas or not isinstance(linhas[0], dict):
        return None
    return parse_estimativa(linhas[0])
