# bucket: always
"""Tool: get_performance_breakdown — consolida os 8 reports Google (Fase 2A).

Aditivo: os reports antigos seguem vivos (tombstone = Fase 2B). Irmão do
meta_get_performance_breakdown (M.4): level + breakdown opcional.
"""

from typing import Any

from src.google_ads.performance_breakdown import (
    _validate_combo,
    build_performance_breakdown_query,
    parse_performance_row,
)
from src.google_ads.queries._common import resolve_date_window
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
            "description": "Dimensao secundaria. So em level=account no v0.",
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
        "custo desc. Para visao geral da conta com comparativo use get_account_overview."
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

    start, end = resolve_date_window(
        date_range=args.get("date_range", "LAST_30_DAYS"),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
    )
    status = args.get("status", "enabled")
    limit = args.get("limit", 100)

    rows = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=build_performance_breakdown_query(level, breakdown, status, start, end, limit),
        row_formatter=lambda row: parse_performance_row(row, level, breakdown),
        operation_name="get_performance_breakdown",
        audit_this_call=True,
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
