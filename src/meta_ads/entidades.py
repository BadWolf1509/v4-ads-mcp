"""Entidades Meta (campanha, conjunto, anuncio) com status e orcamento.

Leitura pura das edges `/{act}/campaigns|adsets|ads`. O orcamento da Graph e string em
centavos; orcamento diario/vitalicio `"0"` (ou ausente) significa "nao tem" e vira `None`.
`budget_remaining` `"0"` e zero MEDIDO (0.0) quando a entidade tem orcamento proprio; sem
orcamento proprio, `None`. Campo que a Meta nao devolveu tambem e `None`.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from src.meta_ads.colecao import ContextoMeta, ler_colecao
from src.meta_ads.reports import run_meta_graph_get

Nivel = Literal["campaign", "adset", "ad"]

_OPERACAO = "meta_get_entities"
_TAMANHO_MAX_PAGINA = 100

_EDGES: dict[str, str] = {"campaign": "campaigns", "adset": "adsets", "ad": "ads"}

# Campos medidos na sonda de 2026-10-31 (docs/operacao/sonda-meta-onda1-2026-10-31.md).
# A edge ignora campo desconhecido em silencio: nao acrescente campo sem medir.
_CAMPOS: dict[str, str] = {
    "campaign": (
        "id,name,status,effective_status,configured_status,objective,buying_type,"
        "daily_budget,lifetime_budget,budget_remaining,bid_strategy,special_ad_categories,"
        "start_time,stop_time,created_time,updated_time,issues_info"
    ),
    "adset": (
        "id,name,campaign_id,status,effective_status,configured_status,daily_budget,"
        "lifetime_budget,budget_remaining,bid_strategy,bid_amount,billing_event,"
        "optimization_goal,destination_type,start_time,end_time,created_time,updated_time,"
        "issues_info,learning_stage_info"
    ),
    "ad": (
        "id,name,adset_id,campaign_id,status,effective_status,configured_status,creative{id},"
        "created_time,updated_time,issues_info,ad_review_feedback"
    ),
}

# Campos copiados como vieram (None quando ausentes), por nivel.
_PASSA: dict[str, tuple[str, ...]] = {
    "campaign": (
        "id",
        "name",
        "status",
        "effective_status",
        "configured_status",
        "objective",
        "buying_type",
        "bid_strategy",
        "special_ad_categories",
        "start_time",
        "stop_time",
        "created_time",
        "updated_time",
        "issues_info",
    ),
    "adset": (
        "id",
        "name",
        "campaign_id",
        "status",
        "effective_status",
        "configured_status",
        "bid_strategy",
        "bid_amount",
        "billing_event",
        "optimization_goal",
        "destination_type",
        "start_time",
        "end_time",
        "created_time",
        "updated_time",
        "issues_info",
        "learning_stage_info",
    ),
    "ad": (
        "id",
        "name",
        "adset_id",
        "campaign_id",
        "status",
        "effective_status",
        "configured_status",
        "created_time",
        "updated_time",
        "issues_info",
        "ad_review_feedback",
    ),
}


def _centavos_para_brl(valor: Any) -> float | None:
    """String em centavos -> BRL. Ausente, `"0"` ou ilegivel -> None (nao reportado)."""
    if valor is None:
        return None
    try:
        centavos = int(str(valor))
    except ValueError:
        return None
    return None if centavos == 0 else centavos / 100


def _restante_para_brl(valor: Any, *, tem_orcamento: bool) -> float | None:
    """`budget_remaining`: `"0"` com orcamento proprio esgotado e 0.0; sem orcamento, None."""
    brl = _centavos_para_brl(valor)
    if brl is not None:
        return brl
    if tem_orcamento and valor is not None:
        try:
            return 0.0 if int(str(valor)) == 0 else None
        except ValueError:
            return None
    return None


def build_entities_call(
    level: Nivel, ad_account_id: str, *, status: str | None, limit: int
) -> tuple[str, dict[str, Any]]:
    """Edge e params da listagem. Pede uma linha a mais que `limit` para provar o truncamento."""
    params: dict[str, Any] = {
        "fields": _CAMPOS[level],
        "limit": min(limit + 1, _TAMANHO_MAX_PAGINA),
    }
    if status:
        params["filtering"] = json.dumps(
            [{"field": "effective_status", "operator": "IN", "value": [status]}],
            separators=(",", ":"),
        )
    return f"/{ad_account_id}/{_EDGES[level]}", params


def parse_entity(level: str, linha: dict[str, Any]) -> dict[str, Any]:
    """Uma linha da Graph -> entidade. Status configurado e efetivo ficam separados."""
    saida: dict[str, Any] = {campo: linha.get(campo) for campo in _PASSA[level]}
    if level in ("campaign", "adset"):
        saida["daily_budget_brl"] = _centavos_para_brl(linha.get("daily_budget"))
        saida["lifetime_budget_brl"] = _centavos_para_brl(linha.get("lifetime_budget"))
        tem = saida["daily_budget_brl"] is not None or saida["lifetime_budget_brl"] is not None
        saida["budget_remaining_brl"] = _restante_para_brl(
            linha.get("budget_remaining"), tem_orcamento=tem
        )
    if level == "adset":
        proprio = saida["daily_budget_brl"] is not None or saida["lifetime_budget_brl"] is not None
        saida["orcamento_em"] = "conjunto" if proprio else "campanha"
    if level == "ad":
        criativo = linha.get("creative")
        saida["creative_id"] = criativo.get("id") if isinstance(criativo, dict) else None
    return saida


async def listar_entidades(
    ctx: ContextoMeta,
    ad_account_id: str,
    level: Nivel,
    status: str | None,
    limit: int,
    operacao: str = _OPERACAO,
) -> tuple[list[dict[str, Any]], bool]:
    """Le as entidades seguindo `paging.next`. Devolve `(entidades, truncated)`.

    `operacao` e o nome sob o qual a leitura e auditada: o chamador passa o seu.
    """
    edge, params = build_entities_call(level, ad_account_id, status=status, limit=limit)
    linhas, sobrou_next = await ler_colecao(
        ctx,
        leitor=run_meta_graph_get,
        ad_account_id=ad_account_id,
        edge=edge,
        params=params,
        operacao=operacao,
        limit=limit,
        params_summary={"ad_account_id": ad_account_id, "level": level, "status": status},
    )
    truncated = len(linhas) > limit or sobrou_next
    return [parse_entity(level, linha) for linha in linhas[:limit]], truncated
