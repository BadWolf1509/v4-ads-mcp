# bucket: defer
"""Tool: get_negative_keywords_audit - campaign-level negative keywords with created_date enrichment."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

from src.google_ads.account_clock import resolve_account_today
from src.google_ads.queries._common import parse_resource_path
from src.google_ads.queries.change_history import negative_criterion_creations_query
from src.google_ads.queries.tactical import negative_keywords_audit_query
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 1000,
            "default": 100,
            "description": (
                "Maximo de negativas retornadas em by_campaign (ordenadas recentes primeiro). "
                "total_negatives + additions_summary refletem conta inteira (nao truncados). "
                "Default 100; aumentar so se necessario (contas grandes podem exceder MCP "
                "response cap acima de ~125 rows)."
            ),
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


def _row_formatter_negatives(row: Any) -> dict[str, Any]:
    return {
        "criterion_id": str(row.campaign_criterion.criterion_id),
        "keyword_text": row.campaign_criterion.keyword.text,
        "match_type": row.campaign_criterion.keyword.match_type.name,
        "campaign_id": str(row.campaign.id),
        "campaign_name": row.campaign.name,
    }


def _row_formatter_creates(row: Any) -> dict[str, Any]:
    return {
        "change_resource_name": str(row.change_event.change_resource_name),
        "change_date_time": str(row.change_event.change_date_time),
        "user_email": str(row.change_event.user_email),
    }


def _build_creations_index(create_rows: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """Map criterion_id -> {created_date, added_by_email} from change_event CREATE rows.

    When multiple CREATE events exist for same criterion_id, picks the MOST RECENT
    by comparing change_date_time strings (ISO-sortable).
    """
    index: dict[str, dict[str, str]] = {}
    for r in create_rows:
        _, compound_id = parse_resource_path(r["change_resource_name"])
        if compound_id is None or "~" not in compound_id:
            continue
        criterion_id = compound_id.split("~", 1)[1]
        # change_date_time is "YYYY-MM-DD HH:MM:SS+TZ" — take date part
        date_part = r["change_date_time"][:10]
        if criterion_id in index:
            # Keep most recent: compare ISO datetime strings (lexicographic = chronological)
            existing_dt = index[criterion_id]["_change_date_time"]
            if r["change_date_time"] <= existing_dt:
                continue  # existing is more recent, skip
        index[criterion_id] = {
            "created_date": date_part,
            "added_by_email": r["user_email"],
            "_change_date_time": r["change_date_time"],
        }
    return index


def _compute_summary(negatives_with_dates: list[dict[str, Any]], today: date) -> dict[str, int]:
    last_7_cutoff = today - timedelta(days=7)
    last_30_cutoff = today - timedelta(days=30)
    last_7 = 0
    last_30 = 0
    unknown = 0
    for n in negatives_with_dates:
        cd = n["created_date"]
        if cd is None:
            unknown += 1
            continue
        cd_parsed = date.fromisoformat(cd)
        if cd_parsed >= last_7_cutoff:
            last_7 += 1
        if cd_parsed >= last_30_cutoff:
            last_30 += 1
    return {
        "last_7_days": last_7,
        "last_30_days": last_30,
        "pre_30_days_or_unknown": unknown,
    }


@register_tool(
    name="get_negative_keywords_audit",
    description=(
        "[DEFER] Lista palavras-chave negativas aplicadas em nivel de campanha, com data "
        "de criacao e usuario que adicionou (quando rastreavel via change_event, "
        "retention ~30 dias). Util pra auditoria de cobertura de negativas, "
        "identificar duplicacoes ou gaps, e narrar 'X negativas adicionadas no "
        "periodo' em report semanal. Bloco additions_summary no root agrega "
        "counts por janela (7d / 30d / pre-30d-ou-desconhecido) — sobre a conta "
        "INTEIRA, nao truncado. by_campaign retorna max `limit` negativas "
        "(default 100, max 1000) ordenadas por adicao recente primeiro. "
        "Quando truncado, response inclui `truncated: true` + `total_negatives` "
        "reflete o universo completo da conta."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def get_negative_keywords_audit(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    limit = args.get("limit", 100)
    # F141: janela `hoje-29..hoje` e os cortes 7d/30d no fuso da CONTA, nao do servidor.
    today = await resolve_account_today(customer_id)
    creates_start = today - timedelta(days=29)
    creates_end = today

    # Parallel: full state of negatives + recent CREATE events for enrichment
    negatives_task = run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=negative_keywords_audit_query(),
        row_formatter=_row_formatter_negatives,
        operation_name="get_negative_keywords_audit",
    )
    creates_task = run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=negative_criterion_creations_query(start=creates_start, end=creates_end),
        row_formatter=_row_formatter_creates,
        operation_name="get_negative_keywords_audit_creations",
    )
    negatives, creates = await asyncio.gather(negatives_task, creates_task)

    creations_index = _build_creations_index(creates)

    enriched: list[dict[str, Any]] = []
    for n in negatives:
        creation = creations_index.get(n["criterion_id"])
        enriched.append(
            {
                **n,
                "created_date": creation["created_date"] if creation else None,
                "added_by_email": creation["added_by_email"] if creation else None,
            }
        )

    total = len(enriched)
    summary = _compute_summary(enriched, today)  # Computed on FULL set, not truncated

    # Prioritize recent first (created_date != null DESC), then unknown (null).
    # Stable sort within each bucket preserves original ordering (campaign-grouping).
    recent = sorted(
        (n for n in enriched if n["created_date"] is not None),
        key=lambda n: n["created_date"],
        reverse=True,
    )
    unknown = [n for n in enriched if n["created_date"] is None]
    prioritized = recent + unknown

    # Truncate to limit
    sliced = prioritized[:limit]
    truncated = total > limit

    # Group by campaign — only what's in the sliced view
    by_campaign: dict[str, dict[str, Any]] = {}
    for n in sliced:
        cid = n["campaign_id"]
        if cid not in by_campaign:
            by_campaign[cid] = {
                "campaign_id": cid,
                "campaign_name": n["campaign_name"],
                "negatives": [],
            }
        by_campaign[cid]["negatives"].append(
            {
                "criterion_id": n["criterion_id"],
                "keyword_text": n["keyword_text"],
                "match_type": n["match_type"],
                "created_date": n["created_date"],
                "added_by_email": n["added_by_email"],
            }
        )

    return {
        "customer_id": customer_id,
        "total_negatives": total,
        "returned_count": len(sliced),
        "truncated": truncated,
        "limit": limit,
        "additions_summary": summary,
        "by_campaign": list(by_campaign.values()),
    }
