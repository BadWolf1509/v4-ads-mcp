# bucket: defer
"""Tool: audit_competitor_keywords — detect competitor brand spending.

Sprint 3b.31 — #6 fila ICE 432 do dogfood MO-JP 2026-05-19.
Detecta gasto em concorrência: positive keywords matching brands + search
terms com cost + sugere negative keywords EXACT+PHRASE per matched brand.
"""

import asyncio
from typing import Any

from src.google_ads.account_clock import resolve_account_today
from src.google_ads.competitor_analysis import match_competitor_brands
from src.google_ads.queries._common import resolve_date_window
from src.google_ads.queries.audit_competitor_keywords import (
    build_positive_keywords_query,
    build_search_terms_query,
    dict_to_keyword_row,
    dict_to_search_term_row,
    parse_positive_keyword_row,
    parse_search_term_row,
)
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "competitor_brands": {
            "type": "array",
            "items": {"type": "string", "minLength": 3, "maxLength": 50},
            "minItems": 1,
            "maxItems": 20,
            "description": (
                "Lista de brand names competidoras pra detectar match. "
                "Min 3 chars cada pra evitar false positives. Max 20 brands. "
                "Match: substring case-insensitive em keyword text + search term."
            ),
        },
        "date_range": {
            "type": "string",
            "enum": ["LAST_7_DAYS", "LAST_14_DAYS", "LAST_30_DAYS", "LAST_90_DAYS"],
            "default": "LAST_7_DAYS",
            "description": "Preset. Override por start_date+end_date se ambos passados.",
        },
        "start_date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        "end_date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 1000,
            "default": 200,
            "description": (
                "Máximo entries por lista (positive_keywords e search_terms). "
                "truncated:true se exceder."
            ),
        },
    },
    "required": ["customer_id", "competitor_brands"],
    "additionalProperties": False,
}


# Extraída do decorator pra virar constante testável (os irmãos de família já
# seguem esse padrão) — o aviso do F90/F52 precisa ser verificável por teste.
_DESCRIPTION = (
    "[DEFER] Detecta gasto em concorrência: keywords positivas ENABLED com text "
    "matching competitor brands + search terms entregues no date window que "
    "matched brand competidora. Output: 2 listas + summary (total cost wasted "
    "real) + suggested_negatives (EXACT + PHRASE per matched brand). Filtros: "
    "competitor_brands[] required (3-50 chars cada, 1-20 brands), date_range "
    "preset OR start_date+end_date custom (default LAST_7_DAYS), limit (default "
    "200, max 1000). Match: substring case-insensitive em keyword text + search "
    "term. Sempre auditado. Nota: cost data Google pode lagar entre queries — "
    "re-query se decisão crítica. "
    "ATENÇÃO (F133): `total_cost_wasted_brl` é CUSTO, não veredito — cada "
    "search term traz `conversions`/`conversions_value_brl` e cada "
    "`suggested_negative` traz `conversions` agregado por brand. **Sugestão "
    "com `conversions > 0` NÃO deve ser aplicada sem cross-check de "
    "catálogo/ERP**: termo de concorrente pode ser o melhor CPA da conta "
    "(caso real: R$ 155,25 / 9 conv = CPA R$ 17,25 contra ~R$ 20 da média). "
    "A tool sinaliza, não decide. "
    "ATENÇÃO (F90/F52): cada positive_keyword traz `ad_group_status`. Keyword "
    "ENABLED dentro de ad_group PAUSED/REMOVED NÃO compete em leilão e não gasta "
    "— filtre `ad_group_status='ENABLED'` antes de agir ou de reportar gasto em "
    "concorrência pro cliente, senão a narrativa infla com item inerte."
)


@register_tool(
    name="audit_competitor_keywords",
    description=_DESCRIPTION,
    input_schema=_SCHEMA,
    bucket="defer",
)
async def audit_competitor_keywords(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    competitor_brands = args["competitor_brands"]
    limit = args.get("limit", 200)

    today = await resolve_account_today(customer_id)
    start_date_obj, end_date_obj = resolve_date_window(
        date_range=args.get("date_range", "LAST_7_DAYS"),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
        today=today,
    )
    start_date = start_date_obj.isoformat()
    end_date = end_date_obj.isoformat()

    pos_query = build_positive_keywords_query()
    st_query = build_search_terms_query(start_date=start_date, end_date=end_date)

    # Parallel via asyncio.gather (latency reduction — 2 queries independent)
    pos_raw, st_raw = await asyncio.gather(
        run_report(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            query=pos_query,
            row_formatter=parse_positive_keyword_row,
            operation_name="audit_competitor_keywords",
            audit_this_call=True,
            params_summary={
                "phase": "positive_keywords",
                "competitor_brands": competitor_brands,
                "limit": limit,
            },
        ),
        run_report(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            query=st_query,
            row_formatter=parse_search_term_row,
            operation_name="audit_competitor_keywords",
            audit_this_call=True,
            params_summary={
                "phase": "search_terms",
                "competitor_brands": competitor_brands,
                "date_window": f"{start_date} to {end_date}",
                "limit": limit,
            },
        ),
    )

    keyword_rows = [dict_to_keyword_row(d) for d in pos_raw]
    search_term_rows = [dict_to_search_term_row(d) for d in st_raw]

    matched_kw, matched_st, suggested, totals, total_cost = match_competitor_brands(
        keyword_rows=keyword_rows,
        search_term_rows=search_term_rows,
        competitor_brands=competitor_brands,
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
        "competitor_brands": competitor_brands,
        "summary": {
            "positive_keywords_count": totals["positive_count"],
            "positive_keywords_truncated": totals["positive_truncated"],
            "search_terms_count": totals["search_count"],
            "search_terms_truncated": totals["search_truncated"],
            "total_cost_wasted_brl": total_cost,
            # F133: `wasted` mantem o nome (contrato em producao) mas nao anda
            # mais sozinho — quem le o veredito le a contra-evidencia junto.
            "total_conversions": totals["total_conversions"],
            "suggested_negatives_count": totals["suggested_count"],
        },
        "positive_keywords": [
            {
                "ad_group_id": k.ad_group_id,
                "ad_group_name": k.ad_group_name,
                "campaign_name": k.campaign_name,
                "keyword_id": k.keyword_id,
                "keyword_text": k.keyword_text,
                "match_type": k.match_type,
                "matched_brand": k.matched_brand,
                "status": k.status,
                "ad_group_status": k.ad_group_status,
            }
            for k in matched_kw
        ],
        "search_terms": [
            {
                "search_term": s.search_term,
                "matched_brand": s.matched_brand,
                "ad_group_name": s.ad_group_name,
                "campaign_name": s.campaign_name,
                "impressions": s.impressions,
                "clicks": s.clicks,
                "cost_brl": s.cost_brl,
                "conversions": s.conversions,
                "conversions_value_brl": s.conversions_value_brl,
            }
            for s in matched_st
        ],
        "suggested_negatives": [
            {
                "text": n.text,
                "match_type": n.match_type,
                "reason": n.reason,
                "conversions": n.conversions,
            }
            for n in suggested
        ],
    }
