# bucket: always
"""Tool: update_keyword_bid - update CPC bids on one or more keywords."""

from typing import Any

from src.db import connection
from src.google_ads.mutations import run_mutation
from src.google_ads.queries._common import (
    micros_to_currency,
    validate_manual_cpc_strategy,
)
from src.google_ads.reports import run_report
from src.governance.blast_radius import RiskLevel, classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._mutate_common import applied_envelope, error_envelope, preview_envelope
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "bids": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ad_group_id": {"type": "string", "pattern": "^[0-9]+$"},
                    "criterion_id": {"type": "string", "pattern": "^[0-9]+$"},
                    "new_cpc_bid_brl": {"type": "number", "minimum": 0},
                },
                "required": ["ad_group_id", "criterion_id", "new_cpc_bid_brl"],
                "additionalProperties": False,
            },
            "minItems": 1,
            "maxItems": 100,
        },
    },
    "required": ["customer_id", "bids"],
    "additionalProperties": False,
}


def _row_formatter(row: Any) -> dict[str, Any]:
    return {
        "ad_group_id": str(row.ad_group.id),
        "criterion_id": str(row.ad_group_criterion.criterion_id),
        "keyword_text": row.ad_group_criterion.keyword.text,
        "current_cpc_bid_micros": int(row.ad_group_criterion.cpc_bid_micros),
    }


@register_tool(
    name="update_keyword_bid",
    description=(
        "[CORE] Atualiza CPC bid de uma ou mais palavras-chave. Cada keyword "
        "identificada por (ad_group_id, criterion_id). Ate 5 keywords com "
        "variacao maxima <=20% auto-aplica; senao retorna preview com token."
    ),
    input_schema=_SCHEMA,
    bucket="always",
)
async def update_keyword_bid(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    bids_input = args["bids"]
    target_count = len(bids_input)

    # F12 pre-flight (Sprint 3b.8): reject if any campaign uses auto-bidding strategy.
    # Google ignora cpc_bid_micros updates silenciosamente em non-MANUAL_CPC strategies.
    ad_group_ids_unique = list({b["ad_group_id"] for b in bids_input})
    strategy_error = await validate_manual_cpc_strategy(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        ad_group_ids=ad_group_ids_unique,
    )
    if strategy_error:
        return error_envelope("update_keyword_bid", strategy_error)

    crit_ids = [b["criterion_id"] for b in bids_input]
    ids_clause = ", ".join(crit_ids)
    query = f"""
        SELECT
          ad_group.id,
          ad_group_criterion.criterion_id,
          ad_group_criterion.keyword.text,
          ad_group_criterion.cpc_bid_micros
        FROM keyword_view
        WHERE ad_group_criterion.criterion_id IN ({ids_clause})
    """.strip()

    rows = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_row_formatter,
        operation_name="update_keyword_bid_lookup",
    )

    by_key = {(r["ad_group_id"], r["criterion_id"]): r for r in rows}
    missing = [
        f"({b['ad_group_id']},{b['criterion_id']})"
        for b in bids_input
        if (b["ad_group_id"], b["criterion_id"]) not in by_key
    ]
    if missing:
        return error_envelope("update_keyword_bid", f"Keywords nao encontradas: {missing}")

    changes: list[dict[str, Any]] = []
    deltas_pct: list[float] = []
    for b in bids_input:
        key = (b["ad_group_id"], b["criterion_id"])
        new_brl = float(b["new_cpc_bid_brl"])
        new_micros = int(new_brl * 1_000_000)
        current_micros = by_key[key]["current_cpc_bid_micros"]
        if current_micros > 0:
            delta_pct = abs(new_micros - current_micros) / current_micros * 100
        else:
            delta_pct = 100.0
        deltas_pct.append(delta_pct)
        changes.append(
            {
                "ad_group_id": b["ad_group_id"],
                "criterion_id": b["criterion_id"],
                "keyword_text": by_key[key]["keyword_text"],
                "current_cpc_bid_brl": micros_to_currency(current_micros),
                "new_cpc_bid_brl": new_brl,
                "delta_pct": round(delta_pct, 2),
                "new_cpc_bid_micros": new_micros,
            }
        )

    max_delta_pct = max(deltas_pct) if deltas_pct else 0.0

    risk = classify(
        operation="update_keyword_bid",
        params={"target_count": target_count, "max_delta_pct": max_delta_pct},
    )

    payload = {
        "bids": [
            {
                "ad_group_id": c["ad_group_id"],
                "criterion_id": c["criterion_id"],
                "new_cpc_bid_micros": c["new_cpc_bid_micros"],
            }
            for c in changes
        ],
        "__target_count__": target_count,
    }
    summary = f"Atualizar CPC de {target_count} keyword(s). Variacao maxima: {max_delta_pct:.1f}%."

    if risk.level == RiskLevel.AUTO:
        result = await run_mutation(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="update_keyword_bid",
            payload=payload,
            target_count=target_count,
        )
        return applied_envelope(
            "update_keyword_bid",
            customer_id,
            summary,
            applied_count=result["applied_count"],
            provider_request_id=result["provider_request_id"],
            auto_applied_reason=risk.reason,
            changes=changes,
        )

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="update_keyword_bid",
            payload=payload,
            blast_summary=summary,
        )
    return preview_envelope(
        "update_keyword_bid",
        customer_id,
        summary,
        token,
        confirmation_reason=risk.reason,
        changes=changes,
        max_delta_pct=round(max_delta_pct, 2),
    )
