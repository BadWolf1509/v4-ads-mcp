"""Historico de alteracoes de uma conta Meta (`/{act}/activities`).

Leitura pura. `since` e `until` (YYYY-MM-DD) sao obrigatorios em TODA chamada: sem eles,
ou com `time_range`, a Meta devolve vazio sem erro (sonda de 2026-10-31). Campo ausente
vira `None`, nunca string vazia.

`since` e `until` da edge se comportam como data UTC (medido no smoke de 02/11: `days=3` com
inicio 31/10 devolveu evento de 30/10 22:25 no fuso da conta). A janela declarada e a do fuso
da conta, entao a chamada pede margem dos dois lados e o filtro por data local decide.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from src.meta_ads.account_clock import resolve_meta_account_zone
from src.meta_ads.colecao import ContextoMeta
from src.meta_ads.errors import MetaAdsFriendlyError
from src.meta_ads.reports import run_meta_graph_get

_OPERACAO = "meta_get_change_history"
_TAMANHO_MAX_PAGINA = 100
# Medido com um evento de 23/10 10:24 UTC: since=22/10 until=23/10 trouxe 0 linhas e
# since=23/10 until=24/10 trouxe 4, entao `since` e inclusivo e `until` e EXCLUSIVO, ambos por
# data UTC. `until` futuro foi aceito em +1 dia, sem erro; +2 nao foi medido.
# Antes: o dia UTC anterior cobre conta a leste de UTC. Depois: +1 cobre o dia UTC seguinte,
# onde cai a noite local a oeste de UTC, e +1 compensa o `until` exclusivo.
_MARGEM_ANTES = timedelta(days=1)
_MARGEM_DEPOIS = timedelta(days=2)
# Paginas alem das necessarias para `limit`, para as linhas fora da janela: uma por lado.
_PAGINAS_DE_MARGEM = 2

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
        "ocorrido_em_fuso_conta": linha.get("date_time_in_timezone"),
        "ator_id": linha.get("actor_id"),
        "ator_nome": linha.get("actor_name"),
        "tipo": linha.get("event_type"),
        "objeto_id": linha.get("object_id"),
        "objeto_nome": linha.get("object_name"),
        "objeto_tipo": _TIPOS_OBJETO.get(tipo_objeto, tipo_objeto)
        if isinstance(tipo_objeto, str)
        else None,
        "detalhe": _detalhe(linha.get("extra_data")),
    }


def build_activities_call(
    ad_account_id: str, *, since: date, until: date, limit: int
) -> tuple[str, dict[str, Any]]:
    """Edge e params de uma pagina. `limit` e o tamanho da pagina, no teto da Graph."""
    return f"/{ad_account_id}/activities", {
        "fields": _CAMPOS,
        "since": since.isoformat(),
        "until": until.isoformat(),
        "limit": min(limit, _TAMANHO_MAX_PAGINA),
    }


def _data_local(event_time: Any, zona: ZoneInfo) -> date | None:
    """Data de `event_time` no fuso da conta. Sem instante absoluto legivel, `None`."""
    if not isinstance(event_time, str):
        return None
    try:
        instante = datetime.fromisoformat(event_time)
    except ValueError:
        return None
    return None if instante.tzinfo is None else instante.astimezone(zona).date()


async def listar_atividades(
    ctx: ContextoMeta, ad_account_id: str, since: date, until: date, limit: int
) -> tuple[list[dict[str, Any]], bool]:
    """Atividades de `since` a `until` no fuso da conta. Devolve `(registros, truncated)`.

    Filtra antes de cortar em `limit`: linha da margem nao consome o limite nem marca
    `truncated`. Sem o fuso da conta, levanta `MetaAdsFriendlyError` (a tool mostra a
    mensagem), mas so DEPOIS da Graph: o gate de acesso mora em `run_meta_graph_get`, e
    gestor sem grant tem de ver a negacao e gerar a linha `denied`, com ou sem fuso. Evento sem data legivel fica, com `data_nao_verificada`: sumir com ele
    esconderia uma alteracao.
    `paging.next` sobrando marca `truncated` mesmo abaixo do limite, porque a ordem das linhas
    nao foi medida e o que ficou para tras pode estar dentro da janela.
    """
    since_graph, until_graph = since - _MARGEM_ANTES, until + _MARGEM_DEPOIS
    edge, params = build_activities_call(
        ad_account_id, since=since_graph, until=until_graph, limit=_TAMANHO_MAX_PAGINA
    )
    max_pages = -(-(limit + 1) // _TAMANHO_MAX_PAGINA) + _PAGINAS_DE_MARGEM
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
            "since_graph": since_graph.isoformat(),
            "until_graph": until_graph.isoformat(),
        },
    )
    fuso = await resolve_meta_account_zone(ad_account_id)
    if not fuso:
        raise MetaAdsFriendlyError(
            f"Conta {ad_account_id} sem fuso legível no inventário: não dá para conferir a "
            "janela do histórico no fuso da conta.",
            retryable=False,
        )
    zona = ZoneInfo(fuso)
    registros: list[dict[str, Any]] = []
    for linha in resp.get("data") or []:
        dia = _data_local(linha.get("event_time"), zona)
        if dia is not None and not since <= dia <= until:
            continue
        registro = parse_atividade(linha)
        if dia is None:
            registro["data_nao_verificada"] = True
        registros.append(registro)
    sobrou_next = bool((resp.get("paging") or {}).get("next"))
    truncated = len(registros) > limit or sobrou_next
    return registros[:limit], truncated
