# bucket: always
"""Tool: get_performance_breakdown — consolida os 8 reports Google (Fase 2A).

Aditivo: os reports antigos seguem vivos (tombstone = Fase 2B). Irmão do
meta_get_performance_breakdown (M.4): level + breakdown opcional.
"""

from typing import Any

from src.google_ads.account_clock import resolve_account_today
from src.google_ads.ad_schedule import BLOCOS_PADRAO, MetricCell, partition_by_blocks
from src.google_ads.performance_breakdown import (
    _validate_combo,
    build_performance_breakdown_query,
    parse_performance_row,
)
from src.google_ads.queries._common import resolve_date_window
from src.google_ads.queries.ad_schedule import day_hour_metrics_query, parse_day_hour_row
from src.google_ads.reports import lookup_country_names, run_report
from src.mcp.context import get_current
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
        "168 x len(campaign_ids) e `truncated` avisando corte. Para visao geral da "
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
    }
