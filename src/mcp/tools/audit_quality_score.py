# bucket: always
"""Tool: audit_quality_score — flag keywords for pause/promote/duplicate intent.

Sprint 3b.30 — #1 fila ICE 504 do dogfood MO-JP 2026-05-19.
Economiza ~30min/sessão em queries manuais de keyword_view.
"""

from typing import Any

from src.google_ads.account_clock import resolve_account_today
from src.google_ads.flag_keywords import flag_keywords
from src.google_ads.queries._common import resolve_date_window
from src.google_ads.queries.audit_quality_score import (
    build_audit_quality_score_query,
    dict_to_keyword_row,
    parse_keyword_view_row,
)
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "ad_group_ids": {
            "type": "array",
            "items": {"type": "string", "pattern": "^[0-9]+$"},
            "minItems": 1,
            "maxItems": 50,
            "description": ("Opcional. Filtra audit a estes ad_group_ids. Default: conta inteira."),
        },
        "min_impressions": {
            "type": "integer",
            "minimum": 1,
            "maximum": 10000,
            "default": 10,
            "description": (
                "Threshold mínimo de impressions pra candidate_pause flag. "
                "Default 10. Reduza pra ~3 em contas low-volume."
            ),
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 1000,
            "default": 200,
            "description": "Máximo keywords retornadas. truncated:true se exceder.",
        },
        "date_range": {
            "type": "string",
            "enum": ["LAST_7_DAYS", "LAST_14_DAYS", "LAST_30_DAYS", "LAST_90_DAYS"],
            "default": "LAST_30_DAYS",
            "description": "Preset. Override por start_date+end_date se ambos passados.",
        },
        "start_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
            "description": (
                "Data inicial YYYY-MM-DD inclusive. Quando informado junto com end_date, "
                "sobrepoe date_range preset. Obriga end_date."
            ),
        },
        "end_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
            "description": "Data final YYYY-MM-DD inclusive. Obrigatorio se start_date informado.",
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


@register_tool(
    name="audit_quality_score",
    description=(
        "[CORE] Identifica keywords problemáticas com 3 flags acionáveis: "
        "candidate_pause (QS<=2 + impressions>=threshold + clicks=0 = waste), "
        "candidate_promote_exact (QS>=7 + BROAD + conv>=1 = promote pra EXACT "
        "reduz CPC), duplicate_intent (mesma keyword text em multi ad_groups, "
        "amplification only — só com outra flag ativa). Output flat list "
        "ordenada QS ASC + impressions DESC tie-break. Filtros: ad_group_ids[], "
        "min_impressions (default 10), limit (default 200, max 1000), date_range "
        "preset OR start_date+end_date custom (default LAST_30_DAYS). Sempre "
        "auditado. Nota: QS pode lagar entre queries (cache Google) — re-query "
        "se decisão crítica baseada em QS. ATENÇÃO (F52): keywords flagged podem "
        "estar em ad_groups REMOVED (órfãs cosméticas — não competem em leilão, "
        "não impactam QS/Smart Bidding). Cada row tem field `ad_group_status` "
        "— filtre `ad_group_status='ENABLED'` no consumer pra cleanup de impacto "
        "técnico real, OU mantenha tudo pra inventário cosmético."
    ),
    input_schema=_SCHEMA,
    bucket="always",
)
async def audit_quality_score(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    ad_group_ids = args.get("ad_group_ids")
    min_impressions = args.get("min_impressions", 10)
    limit = args.get("limit", 200)

    today = await resolve_account_today(customer_id)
    start_date_obj, end_date_obj = resolve_date_window(
        date_range=args.get("date_range", "LAST_30_DAYS"),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
        today=today,
    )

    # Convert date objects to YYYY-MM-DD strings for query builder
    start_date = start_date_obj.isoformat()
    end_date = end_date_obj.isoformat()

    query = build_audit_quality_score_query(
        start_date=start_date,
        end_date=end_date,
        ad_group_ids=ad_group_ids,
    )

    raw_rows = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=parse_keyword_view_row,
        operation_name="audit_quality_score",
        audit_this_call=True,
        params_summary={
            "ad_group_ids": ad_group_ids,
            "min_impressions": min_impressions,
            "limit": limit,
            "date_window": f"{start_date} to {end_date}",
        },
    )

    keyword_rows = [dict_to_keyword_row(d) for d in raw_rows]
    flagged, total = flag_keywords(
        keyword_rows,
        min_impressions=min_impressions,
        limit=limit,
    )

    days = (end_date_obj - start_date_obj).days + 1

    return {
        "customer_id": customer_id,
        "date_range_resolved": {
            "start": start_date,
            "end": end_date,
            "days": days,
        },
        "filters_applied": {
            "ad_group_ids": ad_group_ids,
            "min_impressions": min_impressions,
            "limit": limit,
        },
        "total_flagged": total,
        "truncated": total > limit,
        "flagged_keywords": [
            {
                "ad_group_id": f.ad_group_id,
                "ad_group_name": f.ad_group_name,
                "ad_group_status": f.ad_group_status,  # A2 (espelha F52)
                "campaign_name": f.campaign_name,
                "keyword_id": f.keyword_id,
                "keyword_text": f.keyword_text,
                "match_type": f.match_type,
                "quality_score": f.quality_score,
                "impressions": f.impressions,
                "clicks": f.clicks,
                "conversions": f.conversions,
                "cost_brl": f.cost_brl,
                "flags": list(f.flags),
            }
            for f in flagged
        ],
    }
