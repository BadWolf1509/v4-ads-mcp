# bucket: always
"""Tool: get_performance_breakdown — consolida os 8 reports Google (Fase 2A).

Aditivo: os reports antigos seguem vivos (tombstone = Fase 2B). Irmão do
meta_get_performance_breakdown (M.4): level + breakdown opcional.
"""

from typing import Any

from src.google_ads.account_clock import resolve_account_today
from src.google_ads.ad_schedule import BLOCOS_PADRAO, DIAS, MetricCell, partition_by_blocks
from src.google_ads.performance_breakdown import (
    _validate_combo,
    build_performance_breakdown_query,
    parse_performance_row,
)
from src.google_ads.queries._common import resolve_date_window
from src.google_ads.queries.ad_schedule import day_hour_metrics_query, parse_day_hour_row
from src.google_ads.reports import lookup_country_names, run_report
from src.mcp.context import get_current
from src.mcp.tools._common import aplicar_limite
from src.mcp.tools._registry import register_tool

_DATE_PRESETS = [
    "TODAY",
    "YESTERDAY",
    "LAST_7_DAYS",
    "LAST_14_DAYS",
    "LAST_30_DAYS",
    "LAST_90_DAYS",
    "THIS_MONTH",
    "LAST_MONTH",
    "THIS_WEEK",
    "LAST_WEEK",
]

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "level": {
            "type": "string",
            "enum": ["campaign", "ad_group", "ad", "keyword", "audience", "account"],
            "description": "Granularidade primaria (required).",
        },
        "breakdown": {
            "type": "string",
            "enum": ["device", "geo", "hourly"],
            "description": "Dimensao secundaria. So em level=account no v0, e (Task 5) tambem em level=campaign.",
        },
        "campaign_ids": {
            "type": "array",
            "items": {"type": "string", "pattern": "^[0-9]+$"},
            "maxItems": 20,
            "uniqueItems": True,
            "description": "Obrigatorio so pra level='campaign'+breakdown='hourly': a conjunta dia x hora e cara e nao roda sobre a conta inteira. Ignorado nos demais levels.",
        },
        "date_range": {
            "type": "string",
            "enum": _DATE_PRESETS,
            "default": "LAST_30_DAYS",
            "description": "Periodo via preset. Para periodo custom, use start_date+end_date.",
        },
        "start_date": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
        "end_date": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
        "status": {
            "type": "string",
            "enum": ["enabled", "paused", "removed", "all"],
            "default": "enabled",
            "description": "So entity levels com status (campaign/ad_group/ad/keyword).",
        },
        "limit": {"type": "integer", "minimum": 1, "maximum": 10000, "default": 100},
        "raw_grid": {
            "type": "boolean",
            "default": False,
            "description": "So com level=campaign+breakdown=hourly: devolve as 168 celulas dia x hora por campanha em vez da particao de 3 blocos. Caro; exige campaign_ids curto.",
        },
    },
    "required": ["customer_id", "level"],
    "additionalProperties": False,
}


# Ordem dos dias derivada de `DIAS` (`src/google_ads/ad_schedule.py`), modulo do
# qual esta tool JA importa — duplicar a tupla criaria duas fontes para o mesmo
# enum do Google. O `.get(..., len(DIAS))` manda `UNSPECIFIED`/`UNKNOWN` para o
# fim em vez de estourar `KeyError`: `ENUM_MINUTO` ja trata esses dois valores
# explicitamente para o enum irmao, e ordenacao nao e lugar de descobrir enum
# novo do Google em producao.
_ORDEM_DO_DIA: dict[str, int] = {dia: i for i, dia in enumerate(DIAS)}

# A grade `hourly` da conta tem teto ESTRUTURAL de 168 celulas (7 dias x 24h) —
# nao e uma lista aberta que o `limit` do gestor precise conter. Aplicar o
# default de 100 aqui devolvia 100 das 168, e com a ordem cronologica as 68
# ausentes eram SEMPRE sabado e domingo. Antes deste PR a tool devolvia as 168
# (o builder do `hourly` nao tem clausula LIMIT), entao cortar seria perder dado
# que ja existia, de forma sistematica, na tool que `get_hourly_performance`
# manda preferir. O mesmo idioma ja esta em `campaign+hourly` mais acima:
# `teto = 168 * len(campaign_ids)`, teto da grade, nao do gestor.
_CELULAS_DA_GRADE = 7 * 24


@register_tool(
    name="get_performance_breakdown",
    description=(
        "[CORE] Performance Google quebrada por nivel + dimensao opcional. "
        "level: campaign|ad_group|ad|keyword|audience (rows por entidade) OU "
        "account+breakdown (device|geo|hourly). Metricas: impressions, clicks, "
        "cost_brl, conversions, conversions_value_brl, ctr, cpc_brl. Ordenado por "
        "custo desc. Excecao: level='campaign'+breakdown='hourly' tambem funciona, "
        "mas exige `campaign_ids` (ate 20) — a conjunta dia x hora e cara e nao roda "
        "sobre a conta inteira. Por default devolve a particao em blocos nomeados "
        "(comercial/fora_de_hora/fim_de_semana/outros — BLOCOS_PADRAO), uma linha por "
        "bloco x campanha com cost_brl/conversions/cpa_brl/cells: a grade crua tem 168 "
        "celulas por campanha e o `limit` default (100) truncaria antes de terminar "
        "UMA campanha. `raw_grid: true` troca pela grade crua, com teto "
        "168 x len(campaign_ids) e `truncated` avisando corte. `truncated: true` diz "
        "que havia MAIS linhas do que o teto e a lista foi cortada no topo de gasto — "
        "peca um `limit` maior ou filtre. EXCECAO: em `account+hourly` o teto e "
        "ESTRUTURAL (168 celulas, 7 dias x 24h) e o `limit` NAO se aplica — a grade vem "
        "inteira, em ordem cronologica. ATENCAO (F56): em `level='keyword'` a resposta "
        "traz keyword POSITIVA e NEGATIVA indistintamente — cada row tem `negative: "
        "bool`, filtre `negative=false` no consumer, ou use audit_zombie_keywords, "
        "que filtra `negative = FALSE` server-side (audit_quality_score tambem nao "
        "devolve negativa, mas por outro motivo: ele exige `quality_score IS NOT "
        "NULL`, e criterio negativo nao tem indice de qualidade). Para visao geral da "
        "conta com comparativo use get_account_overview."
    ),
    input_schema=_SCHEMA,
    bucket="always",
)
async def get_performance_breakdown(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    level = args["level"]
    breakdown = args.get("breakdown")

    err = _validate_combo(level, breakdown)
    if err:
        return {"status": "error", "error_message": err}

    today = await resolve_account_today(customer_id)
    start, end = resolve_date_window(
        date_range=args.get("date_range", "LAST_30_DAYS"),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
        today=today,
    )
    status = args.get("status", "enabled")
    limit = args.get("limit", 100)

    if level == "campaign" and breakdown == "hourly":
        # Task 4 deixou `_validate_combo` aceitar este combo mas `build_performance_
        # breakdown_query` recusa com ValueError de proposito (rede de seguranca): a
        # interceptacao TEM que acontecer aqui, antes do builder generico, nunca depois.
        campaign_ids = args.get("campaign_ids") or []
        if not campaign_ids:
            return {
                "status": "error",
                "error_message": "level='campaign' + breakdown='hourly' exige campaign_ids: "
                "a conjunta dia x hora e cara e nao roda sobre a conta inteira.",
            }
        # Fix Important 1 (revisao final): id repetido no input dobrava linhas e
        # custo (loop abaixo itera campaign_ids cru). O schema ja recusa na borda
        # (uniqueItems); isto protege o caminho caso o schema mude. dict.fromkeys
        # dedupe preservando ordem — teto e loop usam a MESMA lista deduplicada.
        campaign_ids = list(dict.fromkeys(campaign_ids))
        teto = 168 * len(campaign_ids)
        celulas = await run_report(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            query=day_hour_metrics_query(campaign_ids=campaign_ids, start=start, end=end),
            row_formatter=parse_day_hour_row,
            operation_name="get_performance_breakdown",
            audit_this_call=True,
            params_summary={"level": level, "breakdown": breakdown},
        )
        truncado = len(celulas) > teto
        if args.get("raw_grid", False):
            return {
                "customer_id": customer_id,
                "level": level,
                "breakdown": breakdown,
                "period": {"from": start.isoformat(), "to": end.isoformat()},
                "rows": celulas[:teto],
                "truncated": truncado,
            }
        linhas: list[dict[str, Any]] = []
        for cid in campaign_ids:
            do_cid = [
                MetricCell(m["day_of_week"], m["hour"], m["cost_micros"], m["conversions"])
                for m in celulas
                if m["campaign_id"] == cid
            ]
            for nome, agg in partition_by_blocks(do_cid, BLOCOS_PADRAO).items():
                linhas.append({"campaign_id": cid, "bloco": nome, **agg})
        return {
            "customer_id": customer_id,
            "level": level,
            "breakdown": breakdown,
            "period": {"from": start.isoformat(), "to": end.isoformat()},
            "rows": linhas,
            "truncated": truncado,
        }

    rows = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=build_performance_breakdown_query(level, breakdown, status, start, end, limit),
        row_formatter=lambda row: parse_performance_row(row, level, breakdown),
        operation_name="get_performance_breakdown",
        audit_this_call=True,
        params_summary={"level": level, "breakdown": breakdown},
    )

    # ANTES do bloco `geo`, nao so antes do `return`: os builders desta tool sao
    # os MESMOS das nove irmas e pedem `limit + 1`, entao a sentinela chegaria ao
    # gestor (`level="keyword", limit=100` -> 101 linhas) e ainda custaria um
    # `geo_target_constant` a mais pra resolver — o custo que `get_geo_performance`
    # foi reordenado pra evitar. Nos dois breakdowns cujo builder nao tem clausula
    # LIMIT (`device`, `hourly`), a API devolve tudo e este corte e o unico lugar
    # onde o `limit` declarado no schema e honrado.
    # `hourly` sai da API sem ORDER BY (o builder nao tem clausula nenhuma), e
    # devolver a grade em ordem arbitraria faz duas chamadas iguais trazerem a
    # mesma grade em ordens diferentes. Cronologica e a unica em que uma grade
    # e legivel, e ordenar aqui nao mexe em GAQL, entao nao muda a ordem de
    # nenhuma outra tool que compartilhe o builder.
    if breakdown == "hourly":
        rows.sort(
            key=lambda r: (
                _ORDEM_DO_DIA.get(r["breakdown"]["day_of_week"], len(DIAS)),
                r["breakdown"]["hour"],
            )
        )

    teto = _CELULAS_DA_GRADE if breakdown == "hourly" else limit
    rows, truncado = aplicar_limite(rows, teto)

    if breakdown == "geo":
        country_ids = {r["breakdown"]["country_criterion_id"] for r in rows}
        country_map = await lookup_country_names(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            country_ids=country_ids,
        )
        for r in rows:
            info = country_map.get(r["breakdown"]["country_criterion_id"])
            r["breakdown"]["country_name"] = info["name"] if info else None
            r["breakdown"]["country_code"] = info["country_code"] if info else None

    return {
        "customer_id": customer_id,
        "level": level,
        "breakdown": breakdown,
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "rows": rows,
        "truncated": truncado,
    }
