"""Sonda os campos e edges das tools Meta da Onda 1 contra a API real.

Read-only: so GET. Imprime formas (chaves, tipos, enums e contagens), nunca valor de cliente nem
o token. Cada edge roda a combinacao completa de `fields` que a tool vai mandar e um CONTROLE com
campo inexistente: edge cujo controle nao erra nao prova nada.

Uso, da raiz do repo, com o token no ambiente:
    META_TOKEN=... python -m scripts.probe_meta_onda1 <act_interna> <act_outra>
"""

import json
import os
import sys
from collections import Counter
from typing import Any

import httpx

from src.meta_ads.client import META_GRAPH_API_VERSION

_BASE = f"https://graph.facebook.com/{META_GRAPH_API_VERSION}"
_CAMPO_INVALIDO = "campo_que_nao_existe_v4"
_ENUMS = {
    "status",
    "effective_status",
    "configured_status",
    "objective",
    "buying_type",
    "bid_strategy",
    "billing_event",
    "optimization_goal",
    "destination_type",
    "event_type",
    "object_type",
    "subtype",
    "call_to_action_type",
}

CAMPOS = {
    "campaigns": (
        "id,name,status,effective_status,configured_status,objective,buying_type,daily_budget,"
        "lifetime_budget,budget_remaining,bid_strategy,special_ad_categories,start_time,stop_time,"
        "created_time,updated_time,issues_info"
    ),
    "adsets": (
        "id,name,campaign_id,status,effective_status,configured_status,daily_budget,"
        "lifetime_budget,budget_remaining,bid_strategy,bid_amount,billing_event,optimization_goal,"
        "destination_type,start_time,end_time,created_time,updated_time,issues_info,"
        "learning_stage_info"
    ),
    "ads": (
        "id,name,adset_id,campaign_id,status,effective_status,configured_status,creative{id},"
        "created_time,updated_time,issues_info,ad_review_feedback"
    ),
    "activities": (
        "actor_id,actor_name,application_id,application_name,date_time_in_timezone,event_time,"
        "event_type,extra_data,object_id,object_name,object_type,translated_event_type"
    ),
    "adcreatives": (
        "id,name,status,object_type,title,body,image_url,thumbnail_url,call_to_action_type,"
        "object_story_id,effective_object_story_id,instagram_permalink_url"
    ),
    "customaudiences": (
        "id,name,subtype,description,approximate_count_lower_bound,approximate_count_upper_bound,"
        "delivery_status,operation_status,retention_days,time_created,time_updated"
    ),
    "adspixels": (
        "id,name,last_fired_time,is_unavailable,creation_time,first_party_cookie_status,"
        "enable_automatic_matching"
    ),
    "promote_pages": "id,name,instagram_business_account,connected_instagram_account",
    "instagram_accounts": "id,username",
    "connected_instagram_accounts": "id,username",
}


def _forma(valor: Any) -> Any:
    if isinstance(valor, dict):
        return {k: _forma(v) for k, v in sorted(valor.items())}
    if isinstance(valor, list):
        return [_forma(valor[0])] if valor else []
    return type(valor).__name__


def _erro(corpo: dict[str, Any]) -> dict[str, Any] | None:
    e = corpo.get("error")
    if not e:
        return None
    return {k: e.get(k) for k in ("code", "error_subcode", "type", "message")}


def _resumo(http: httpx.Client, act: str, edge: str, params: dict[str, Any]) -> dict[str, Any]:
    r = http.get(f"{_BASE}/{act}/{edge}", params=params)
    corpo = r.json()
    linhas = corpo.get("data") if isinstance(corpo.get("data"), list) else []
    chaves: Counter[str] = Counter()
    enums: dict[str, set[str]] = {}
    formas: dict[str, Any] = {}
    for linha in linhas:
        for k, v in linha.items():
            chaves[k] += 1
            formas.setdefault(k, _forma(v))
            if k in _ENUMS and isinstance(v, str):
                enums.setdefault(k, set()).add(v)
    return {
        "http": r.status_code,
        "erro": _erro(corpo),
        "linhas": len(linhas),
        "paging": sorted(corpo.get("paging", {})),
        "tem_next": "next" in corpo.get("paging", {}),
        "chaves": dict(chaves),
        "formas": formas,
        "enums": {k: sorted(v) for k, v in enums.items()},
        "topo": sorted(corpo),
    }


def _sondar(act: str, outra: str, token: str) -> dict[str, Any]:
    r: dict[str, Any] = {}
    cabecalhos = {"Authorization": f"Bearer {token}"}
    with httpx.Client(headers=cabecalhos, timeout=60) as http:
        for edge, campos in CAMPOS.items():
            r[edge] = {
                "real": _resumo(http, act, edge, {"fields": campos, "limit": 50}),
                "controle": _resumo(
                    http, act, edge, {"fields": f"id,{_CAMPO_INVALIDO}", "limit": 1}
                ),
            }
            r[edge]["controle"] = {k: r[edge]["controle"][k] for k in ("http", "erro", "linhas")}

        ativos = json.dumps([{"field": "effective_status", "operator": "IN", "value": ["PAUSED"]}])
        r["filtro_status"] = _resumo(
            http, act, "campaigns", {"fields": "id,effective_status", "filtering": ativos}
        )

        # stats e qualidade do pixel por expansao, sem sair do edge da conta (F190).
        r["pixel_stats_aninhado"] = _resumo(
            http,
            act,
            "adspixels",
            {"fields": "id,stats.aggregation(event){data,start_time,aggregation}", "limit": 5},
        )

        alvo = json.dumps({"geo_locations": {"countries": ["BR"]}})
        r["reachestimate"] = _resumo(http, act, "reachestimate", {"targeting_spec": alvo})
        r["delivery_estimate"] = _resumo(
            http,
            act,
            "delivery_estimate",
            {"targeting_spec": alvo, "optimization_goal": "REACH"},
        )
        r["delivery_estimate_controle"] = _resumo(
            http, act, "delivery_estimate", {"targeting_spec": "{", "optimization_goal": "REACH"}
        )
        r["targetingsearch"] = _resumo(http, act, "targetingsearch", {"q": "marketing", "limit": 5})
        r["targetingsearch_controle"] = _resumo(http, act, "targetingsearch", {"limit": 5})

        criativos = http.get(
            f"{_BASE}/{act}/adcreatives", params={"fields": "id", "limit": 1}
        ).json()
        ids = [c["id"] for c in criativos.get("data", [])]
        if ids:
            cid = ids[0]
            for nome, corpo_criativo in (
                ("id", {"id": cid}),
                ("creative_id", {"creative_id": cid}),
            ):
                r[f"preview_por_{nome}"] = _resumo(
                    http,
                    act,
                    "generatepreviews",
                    {"ad_format": "MOBILE_FEED_STANDARD", "creative": json.dumps(corpo_criativo)},
                )
            r["preview_formato_invalido"] = _resumo(
                http,
                act,
                "generatepreviews",
                {"ad_format": "FORMATO_INVALIDO", "creative": json.dumps({"id": cid})},
            )
            # Criativo da conta A pedido pelo edge da conta B: a recusa e o que a Task 4 presume.
            r["preview_criativo_de_outra_conta"] = _resumo(
                http,
                outra,
                "generatepreviews",
                {"ad_format": "MOBILE_FEED_STANDARD", "creative": json.dumps({"id": cid})},
            )
        else:
            r["preview"] = "conta sem criativo: nao medido"
    return r


def _sondar_interna(act: str, token: str) -> dict[str, Any]:
    """2a rodada, so na conta interna: lista de campos por `metadata=1` e valores de orcamento."""
    r: dict[str, Any] = {}
    with httpx.Client(headers={"Authorization": f"Bearer {token}"}, timeout=60) as http:
        ids = {}
        for edge in ("campaigns", "adsets", "ads", "adcreatives"):
            linhas = http.get(f"{_BASE}/{act}/{edge}", params={"fields": "id", "limit": 1}).json()
            ids[edge] = linhas["data"][0]["id"]
        for edge, oid in ids.items():
            meta = http.get(f"{_BASE}/{oid}", params={"metadata": 1}).json()
            existentes = {c["name"] for c in meta.get("metadata", {}).get("fields", [])}
            pedidos = {c.split("{")[0] for c in CAMPOS[edge].split(",")}
            invalido = http.get(f"{_BASE}/{oid}", params={"fields": _CAMPO_INVALIDO}).json()
            r[f"metadata_{edge}"] = {
                "total": len(existentes),
                "pedidos_inexistentes": sorted(pedidos - existentes),
                "candidatos": sorted(
                    existentes
                    & {
                        "issues_info",
                        "recommendations",
                        "bid_amount",
                        "learning_stage_info",
                        "ad_review_feedback",
                        "smart_promotion_type",
                        "pacing_type",
                        "daily_min_spend_target",
                        "bid_constraints",
                    }
                ),
                "controle_no_objeto": _erro(invalido),
            }
        conjunto = http.get(
            f"{_BASE}/{act}/adsets",
            params={"fields": "daily_budget,lifetime_budget,budget_remaining", "limit": 1},
        ).json()["data"][0]
        campanha = http.get(
            f"{_BASE}/{act}/campaigns",
            params={"fields": "daily_budget,lifetime_budget,budget_remaining", "limit": 1},
        ).json()["data"][0]
        r["orcamento_bruto"] = {"conjunto": conjunto, "campanha": campanha}
        preview = http.get(
            f"{_BASE}/{act}/generatepreviews",
            params={
                "ad_format": "MOBILE_FEED_STANDARD",
                "creative": json.dumps({"id": ids["adcreatives"]}),
            },
        ).json()["data"][0]["body"]
        r["preview_body"] = {
            "inicio": preview[:8],
            "tem_iframe": "<iframe" in preview,
            "dominio_src": preview.split('src="', 1)[-1].split("/")[2],
        }
        for nome, params in (
            ("sem_periodo", {}),
            ("since_until_90d", {"since": "2026-08-03", "until": "2026-11-01"}),
            (
                "time_range",
                {"time_range": json.dumps({"since": "2026-08-03", "until": "2026-11-01"})},
            ),
        ):
            r[f"activities_{nome}"] = _resumo(
                http, act, "activities", {"fields": CAMPOS["activities"], "limit": 25, **params}
            )
    return r


def main() -> int:
    token = os.environ["META_TOKEN"]
    if len(sys.argv) == 2:
        resultado = _sondar_interna(sys.argv[1], token)
    else:
        resultado = _sondar(sys.argv[1], sys.argv[2], token)
    print(json.dumps(resultado, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
