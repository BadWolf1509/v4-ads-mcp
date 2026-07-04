# bucket: defer
"""Tool: update_ad_group_bid - update CPC bids on one or more ad groups."""

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
                    "new_cpc_bid_brl": {"type": "number", "minimum": 0},
                },
                "required": ["ad_group_id", "new_cpc_bid_brl"],
                "additionalProperties": False,
            },
            "minItems": 1,
            "maxItems": 50,
        },
    },
    "required": ["customer_id", "bids"],
    "additionalProperties": False,
}


def _row_formatter(row: Any) -> dict[str, Any]:
    return {
        "ad_group_id": str(row.ad_group.id),
        "ad_group_name": row.ad_group.name,
        "current_cpc_bid_micros": int(row.ad_group.cpc_bid_micros),
    }


@register_tool(
    name="update_ad_group_bid",
    description=(
        "[DEFER] Atualiza CPC bid de um ou mais grupos de anuncios. Ate 5 grupos com "
        "variacao maxima <=20% auto-aplica; senao retorna preview com token."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def update_ad_group_bid(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    bids_input = args["bids"]
    target_count = len(bids_input)

    # F12 pre-flight (Sprint 3b.8): reject if any campaign uses auto-bidding strategy.
    # Google ignora cpc_bid_micros updates silenciosamente em non-MANUAL_CPC strategies.
    ad_group_ids_check = [b["ad_group_id"] for b in bids_input]
    strategy_error = await validate_manual_cpc_strategy(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        ad_group_ids=ad_group_ids_check,
    )
    if strategy_error:
        return error_envelope("update_ad_group_bid", strategy_error)

    # Resolve current bids via GAQL
    ag_ids = [b["ad_group_id"] for b in bids_input]
    ids_clause = ", ".join(ag_ids)
    query = f"""
        SELECT ad_group.id, ad_group.name, ad_group.cpc_bid_micros
        FROM ad_group
        WHERE ad_group.id IN ({ids_clause})
    """.strip()

    rows = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_row_formatter,
        operation_name="update_ad_group_bid_lookup",
    )

    by_id = {r["ad_group_id"]: r for r in rows}
    missing = [b["ad_group_id"] for b in bids_input if b["ad_group_id"] not in by_id]
    if missing:
        return error_envelope("update_ad_group_bid", f"Ad groups nao encontrados: {missing}")

    # Build per-bid changes + compute max_delta_pct
    changes: list[dict[str, Any]] = []
    deltas_pct: list[float] = []
    for b in bids_input:
        agid = b["ad_group_id"]
        new_brl = float(b["new_cpc_bid_brl"])
        new_micros = int(new_brl * 1_000_000)
        current_micros = by_id[agid]["current_cpc_bid_micros"]
        if current_micros > 0:
            delta_pct = abs(new_micros - current_micros) / current_micros * 100
        else:
            # No current bid (group inherits from campaign) — treat as full change
            delta_pct = 100.0
        deltas_pct.append(delta_pct)
        changes.append(
            {
                "ad_group_id": agid,
                "ad_group_name": by_id[agid]["ad_group_name"],
                "current_cpc_bid_brl": micros_to_currency(current_micros),
                "new_cpc_bid_brl": new_brl,
                "delta_pct": round(delta_pct, 2),
                "new_cpc_bid_micros": new_micros,
            }
        )

    max_delta_pct = max(deltas_pct) if deltas_pct else 0.0

    risk = classify(
        operation="update_ad_group_bid",
        params={"target_count": target_count, "max_delta_pct": max_delta_pct},
    )

    payload = {
        "bids": [
            {"ad_group_id": c["ad_group_id"], "new_cpc_bid_micros": c["new_cpc_bid_micros"]}
            for c in changes
        ],
        "__target_count__": target_count,
    }
    summary = f"Atualizar CPC de {target_count} grupo(s). Variacao maxima: {max_delta_pct:.1f}%."

    if risk.level == RiskLevel.AUTO:
        result = await run_mutation(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="update_ad_group_bid",
            payload=payload,
            target_count=target_count,
        )
        return applied_envelope(
            "update_ad_group_bid",
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
            operation_type="update_ad_group_bid",
            payload=payload,
            blast_summary=summary,
        )
    return preview_envelope(
        "update_ad_group_bid",
        customer_id,
        summary,
        token,
        confirmation_reason=risk.reason,
        changes=changes,
        max_delta_pct=round(max_delta_pct, 2),
    )
