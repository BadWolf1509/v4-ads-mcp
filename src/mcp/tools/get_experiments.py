# bucket: defer
"""Tool: get_experiments — experimentos Google Ads + comparativo base x variacao (G1).

A API nao liga braco a anuncio (F181): `experiment_arm` so traz `resource_name` e
`experiment`. As variacoes de um experimento AD_VARIATION sao RSAs com
`system_managed_resource_source = AD_VARIATIONS`, e a unica forma honesta de liga-las
a um experimento e por ELIMINACAO: so quando a conta tem exatamente UM AD_VARIATION
ENABLED. Com 0 ou 2+ a resposta diz `atribuicao: null` e o motivo — nunca chuta.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from src.google_ads.account_clock import resolve_account_today
from src.google_ads.queries._common import micros_to_currency
from src.google_ads.queries.experiments import (
    anuncios_query,
    experimentos_query,
    metricas_query,
    parse_anuncio_row,
    parse_experimento_row,
    parse_metrica_row,
)
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool
from src.razoes import razao

COMO_APLICAR = (
    "Para aplicar o resultado: update_rsa nos base_ad_ids do grupo — a variacao herda a "
    "mudanca em minutos (F181); ler cedo demais devolve o estado antigo sem erro."
)
AVISO = (
    "Comparativo somado por grupo; nao e o teste de significancia da UI (a API nao o "
    "expoe). A API nao liga braco a anuncio (F181)."
)
ATRIBUICAO_INFERIDA = "inferida_por_eliminacao"

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "experiment_id": {
            "type": "string",
            "pattern": "^[0-9]+$",
            "description": "Opcional. Lista so este experimento; a regra de atribuicao "
            "continua sendo sobre a conta inteira.",
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}

_DESCRIPTION = (
    "[DEFER] Experimentos Google Ads da conta (id, nome, tipo, status, inicio, fim) e, "
    "para o experimento de variacao de anuncio (AD_VARIATION) ENABLED, o comparativo por "
    "grupo: base (RSAs ENABLED sem AD_VARIATIONS) x variacao (RSAs ENABLED com "
    "system_managed_resource_source = AD_VARIATIONS), cada lado SOMADO com impressions, "
    "clicks, cost_brl, conversions e cpa_brl (null com 0 conversao). Lista todos os "
    "`base_ad_ids` e `variacao_ad_ids` do grupo, sem parear base com variacao; so entram "
    "grupos com variacao ENABLED; grupo sem base ENABLED vem com `base: null`. Anuncio sem "
    "trafego na janela conta como zero (nao some). ATRIBUICAO: a API nao liga braco a "
    "anuncio (F181), entao as variacoes so se atribuem ao experimento por eliminacao — "
    "quando a conta tem exatamente UM AD_VARIATION ENABLED (`atribuicao: "
    "'inferida_por_eliminacao'`). Com 0 ou 2+, `atribuicao: null`, `atribuicao_motivo` "
    "diz por que, e todo experimento vem com `grupos: null` — null e 'nao da para "
    "atribuir', nao 'sem grupos'. Experimento REMOVED, PAUSED ou de outro tipo (ex.: "
    "SEARCH_CUSTOM, de campanha) vem so na lista, com `grupos: null`. `experiment_id` "
    "filtra a lista, mas a regra continua sendo sobre a conta. `janela` (inicio, fim) "
    "declara o periodo das metricas: inicio do experimento -> min(ontem no fuso da conta, "
    "fim do experimento); experimento que ainda nao comecou vem com `janela: null` e "
    "metricas null. Nao e o teste de significancia da UI (`aviso`); `como_aplicar` diz "
    "como aplicar o resultado (update_rsa nos base_ad_ids). Razao com denominador zero "
    "vem null (indefinida), nao 0."
)


def _vazia() -> dict[str, Any]:
    return {"impressions": 0, "clicks": 0, "cost_micros": 0, "conversions": 0.0}


def _metricas(ad_ids: list[str], linhas: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """Soma os anuncios do lado; anuncio sem linha de metrica conta como zero."""
    if not ad_ids:
        return None
    soma = _vazia()
    for ad_id in ad_ids:
        m = linhas.get(ad_id, _vazia())
        for k in soma:
            soma[k] += m[k]
    custo = micros_to_currency(soma["cost_micros"])
    conv = float(soma["conversions"])
    cpa = razao(custo, conv)
    return {
        "impressions": int(soma["impressions"]),
        "clicks": int(soma["clicks"]),
        "cost_brl": round(custo, 2),
        "conversions": round(conv, 2),
        "cpa_brl": round(cpa, 2) if cpa is not None else None,
    }


def _janela(exp: dict[str, Any], *, hoje: date) -> tuple[date, date] | None:
    if not exp["inicio"]:
        return None
    inicio = date.fromisoformat(exp["inicio"])
    fim = hoje - timedelta(days=1)
    if exp["fim"]:
        fim = min(fim, date.fromisoformat(exp["fim"]))
    if inicio > fim:  # experimento ainda nao comecou (ou nao fechou nenhum dia)
        return None
    return inicio, fim


def _ordenados(ids: list[str]) -> list[str]:
    return sorted(set(ids), key=int)


@register_tool(
    name="get_experiments", description=_DESCRIPTION, input_schema=_SCHEMA, bucket="defer"
)
async def get_experiments(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    experiment_id = args.get("experiment_id")

    async def _consulta(query: str, parser: Any, *, audited: bool = False) -> list[dict[str, Any]]:
        return await run_report(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            query=query,
            row_formatter=parser,
            operation_name="get_experiments",
            audit_this_call=audited,
            params_summary={"experiment_id": experiment_id} if audited else None,
        )

    # Sempre le TODOS os experimentos: a eliminacao e uma regra sobre a CONTA, nao sobre
    # o filtro. Filtrar no GAQL faria um experiment_id qualquer parecer o "unico ENABLED".
    todos = await _consulta(experimentos_query(None), parse_experimento_row, audited=True)
    ad_variation_enabled = [
        e for e in todos if e["tipo"] == "AD_VARIATION" and e["status"] == "ENABLED"
    ]
    listados = [e for e in todos if experiment_id is None or e["experiment_id"] == experiment_id]

    alvo = ad_variation_enabled[0] if len(ad_variation_enabled) == 1 else None
    if len(ad_variation_enabled) == 0:
        motivo = (
            "Nenhum experimento AD_VARIATION ENABLED na conta: nao ha variacao em teste "
            "para atribuir."
        )
    elif alvo is None:
        motivo = (
            f"{len(ad_variation_enabled)} experimentos AD_VARIATION ENABLED na conta: a API "
            "nao liga braco a anuncio (F181), entao nao da para dizer de qual experimento "
            "e cada variacao."
        )
    elif alvo not in listados:
        motivo = (
            f"O unico AD_VARIATION ENABLED da conta e o {alvo['experiment_id']}, fora do "
            "filtro: o experimento listado nao recebe atribuicao."
        )
        alvo = None
    else:
        motivo = (
            f"Unico AD_VARIATION ENABLED da conta: as variacoes ENABLED (AD_VARIATIONS) sao "
            f"atribuidas ao {alvo['experiment_id']} por eliminacao; a API nao liga braco a "
            "anuncio (F181)."
        )

    experimentos = [{**e, "grupos": None} for e in listados]
    janela: dict[str, str] | None = None

    if alvo is not None:
        hoje = await resolve_account_today(customer_id)
        intervalo = _janela(alvo, hoje=hoje)
        anuncios = await _consulta(anuncios_query(), parse_anuncio_row)

        grupos: dict[str, dict[str, Any]] = {}
        for a in anuncios:
            g = grupos.setdefault(
                a["ad_group_id"],
                {
                    "ad_group_id": a["ad_group_id"],
                    "ad_group": a["ad_group"],
                    "campanha": a["campanha"],
                    "base_ad_ids": [],
                    "variacao_ad_ids": [],
                },
            )
            g["variacao_ad_ids" if a["variacao"] else "base_ad_ids"].append(a["ad_id"])
        com_variacao = [g for g in grupos.values() if g["variacao_ad_ids"]]

        linhas: dict[str, dict[str, dict[str, Any]]] = {}
        if intervalo is not None:
            inicio, fim = intervalo
            janela = {"inicio": inicio.isoformat(), "fim": fim.isoformat()}
        if intervalo is not None and com_variacao:
            metricas = await _consulta(
                metricas_query([g["ad_group_id"] for g in com_variacao], start=inicio, end=fim),
                parse_metrica_row,
            )
            for m in metricas:
                acum = linhas.setdefault(m["ad_group_id"], {}).setdefault(m["ad_id"], _vazia())
                for k in acum:
                    acum[k] += m[k]

        saida: list[dict[str, Any]] = []
        for g in sorted(com_variacao, key=lambda x: int(x["ad_group_id"])):
            base_ids = _ordenados(g["base_ad_ids"])
            var_ids = _ordenados(g["variacao_ad_ids"])
            do_grupo = linhas.get(g["ad_group_id"], {})
            saida.append(
                {
                    **g,
                    "base_ad_ids": base_ids,
                    "variacao_ad_ids": var_ids,
                    "base": _metricas(base_ids, do_grupo) if janela else None,
                    "variacao": _metricas(var_ids, do_grupo) if janela else None,
                }
            )
        for e in experimentos:
            if e["experiment_id"] == alvo["experiment_id"]:
                e["grupos"] = saida

    return {
        "experimentos": experimentos,
        "atribuicao": ATRIBUICAO_INFERIDA if alvo is not None else None,
        "atribuicao_motivo": motivo,
        "janela": janela,
        "como_aplicar": COMO_APLICAR,
        "aviso": AVISO,
    }
