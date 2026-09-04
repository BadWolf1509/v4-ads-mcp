# bucket: defer
"""Tool: get_ad_schedule — grade de veiculacao (dia x hora) por campanha (spec §3).

Campanha SEM criterio de AD_SCHEDULE serve 24x7. Essa distincao nao pode
ficar implicita numa lista vazia — mesma classe do F131 (vazio que quer dizer
duas coisas). Por isso `schedule_summary` existe por campanha, mesmo sem janela.
"""

import asyncio
from typing import Any

from src.google_ads.ad_schedule import CurrentWindow, Window, summarize_current
from src.google_ads.queries.ad_schedule import (
    ad_schedule_query,
    campaign_budget_query,
    parse_ad_schedule_row,
    parse_campaign_budget_row,
)
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "campaign_ids": {
            "type": "array",
            "items": {"type": "string", "pattern": "^[0-9]+$"},
            "minItems": 1,
            "maxItems": 50,
            "description": "Opcional. Default: conta inteira.",
        },
        "status": {
            "type": "string",
            "enum": ["enabled", "paused", "removed", "all"],
            "default": "enabled",
            "description": "Status dos CRITERIOS de agenda (nao da campanha).",
        },
        "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}

_DESCRIPTION = (
    "[DEFER] Grade de veiculacao (ad schedule) por campanha: uma linha por janela "
    "(day_of_week, start_hour/minute, end_hour/minute, bid_modifier, status, "
    "criterion_id, resource_name) e um `schedule_summary` por campanha com "
    "`has_schedule`, `hours_per_week`, `budget_is_shared` e `campaign_status` "
    "(grade de campanha PAUSED nao afeta entrega). ATENCAO: campanha "
    "SEM nenhuma janela serve 24x7 — `has_schedule: false` e `hours_per_week: 168` "
    "dizem isso explicitamente; nao leia lista vazia como 'nao serve'. Janela cobre "
    "[inicio, fim); `end_hour: 24` = ate o fim do dia; minutos so 0/15/30/45 (API). "
    "Uma campanha pode ter ate 7x24 janelas: `limit` (default 200, teto 1000) corta e "
    "`truncated: true` avisa. `budget_is_shared` vem de campaign_budget.explicitly_shared "
    "— importa porque desligar faixa em orcamento compartilhado REALOCA gasto, nao "
    "economiza (ver update_ad_schedule)."
)


def rows_to_current(rows: list[dict[str, Any]]) -> dict[str, list[CurrentWindow]]:
    """Linhas do parser -> CurrentWindow por campanha (reusado pelo update_ad_schedule)."""
    por_campanha: dict[str, list[CurrentWindow]] = {}
    for r in rows:
        w = Window(
            r["day_of_week"], r["start_hour"], r["start_minute"], r["end_hour"], r["end_minute"]
        )
        por_campanha.setdefault(r["campaign_id"], []).append(
            CurrentWindow(
                window=w,
                resource_name=r["resource_name"],
                criterion_id=r["criterion_id"],
                bid_modifier=r["bid_modifier"],
            )
        )
    return por_campanha


@register_tool(
    name="get_ad_schedule", description=_DESCRIPTION, input_schema=_SCHEMA, bucket="defer"
)
async def get_ad_schedule(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    campaign_ids = args.get("campaign_ids")
    status = args.get("status", "enabled")
    limit = args.get("limit", 200)

    async def _consulta(query: str, parser: Any, *, audited: bool = False) -> list[dict[str, Any]]:
        return await run_report(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            query=query,
            row_formatter=parser,
            operation_name="get_ad_schedule",
            audit_this_call=audited,
            params_summary=(
                {"campaign_ids": campaign_ids, "status": status, "limit": limit}
                if audited
                else None
            ),
        )

    grade_rows, orcamentos = await asyncio.gather(
        _consulta(
            ad_schedule_query(campaign_ids=campaign_ids, status=status, limit=limit),
            parse_ad_schedule_row,
            audited=True,
        ),
        _consulta(campaign_budget_query(campaign_ids=campaign_ids), parse_campaign_budget_row),
    )
    truncated = len(grade_rows) > limit
    grade_rows = grade_rows[:limit]

    atual = rows_to_current(grade_rows)
    summary: dict[str, dict[str, Any]] = {}
    for o in orcamentos:
        cid = o["campaign_id"]
        summary[cid] = {
            "campaign_name": o["campaign_name"],
            # F52/F90: grade de campanha PAUSED nao afeta entrega. Sem o status, o
            # resumo descreve horas servidas de uma campanha que nao serve nenhuma.
            "campaign_status": o["status"],
            **summarize_current(atual.get(cid, [])),
            "budget_is_shared": o["explicitly_shared"],
        }
    return {
        "customer_id": customer_id,
        "windows": grade_rows,
        "schedule_summary": summary,
        "truncated": truncated,
    }
