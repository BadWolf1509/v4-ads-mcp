# bucket: defer
"""Tool: add_keywords - create new positive keywords in 1 ad_group.

Workflow: gestor identifies needed keyword variations (typically via
analise-performance skill or briefing) and adds them with chosen
match_type. Combined with update_keyword_status (pause old) +
add_negatives_from_search_terms (block bad terms), this completes the
'pause underperformer + add replacement' workflow.

Up to 500 per call. AUTO ≤20 per spec §7.1.

Idempotency note (Sprint 3b.3 smoke 2026-05-12 finding A1):
Re-adding the same (text, match_type) into the same ad_group is
**state-idempotent** but the API surfaces this via Google's server-side
silent dedupe — NOT via a CRITERION_EXISTS partial_failure error. So
the returned per-row `status` will be `"added"` on the duplicate call
(not `"already_exists"`), and no second criterion is created. The
`_classify_partial` mapping for `CRITERION_EXISTS` / `DUPLICATE_KEYWORD`
is kept as a defensive guard in case Google changes the behavior, but
in practice today it does not fire.
"""

from collections import Counter
from typing import Any

from src.db import connection
from src.google_ads.mutations import run_mutation
from src.governance.blast_radius import RiskLevel, classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._common import classify_partial
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "ad_group_id": {"type": "string", "pattern": "^[0-9]+$"},
        "keywords": {
            "type": "array",
            "minItems": 1,
            "maxItems": 500,
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "minLength": 1, "maxLength": 80},
                    "match_type": {
                        "type": "string",
                        "enum": ["EXACT", "PHRASE", "BROAD"],
                    },
                    "cpc_bid_micros": {"type": "integer", "minimum": 1},
                },
                "required": ["text", "match_type"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["customer_id", "ad_group_id", "keywords"],
    "additionalProperties": False,
}


# Google Ads error codes that indicate the criterion already exists (idempotent case).
_ALREADY_EXISTS_PATTERNS = (
    "CRITERION_EXISTS",
    "DUPLICATE_KEYWORD",
)


def _build_params_summary(ad_group_id: str, keywords: list[dict[str, Any]]) -> dict[str, Any]:
    """Audit-safe summary: aggregate metadata only, never the texts (spec §3.6)."""
    match_types = Counter(kw["match_type"].upper() for kw in keywords)
    with_bid = sum(1 for kw in keywords if "cpc_bid_micros" in kw)
    return {
        "ad_group_id": ad_group_id,
        "match_types_distribution": dict(match_types),
        "with_custom_bid_count": with_bid,
    }


@register_tool(
    name="add_keywords",
    description=(
        "[DEFER] Cria N novas palavras-chave positivas em 1 ad_group. Cada keyword tem "
        "text + match_type (EXACT|PHRASE|BROAD) + cpc_bid_micros opcional (herda "
        "do ad_group se omitido). Ate 500 por chamada. AUTO se ≤20 (spec §7.1), "
        "CONFIRM se >20. Idempotente state-wise (Google deduplica server-side se "
        "rodar 2x com mesmo text+match_type — sem criar criterion duplicada). "
        "Use com update_keyword_status (pausar antigas) + "
        "add_negatives_from_search_terms (bloquear termos ruins) pra workflow "
        "completo de 'pausa + adiciona' da skill analise-performance."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def add_keywords(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    ad_group_id = args["ad_group_id"]
    keywords = args["keywords"]
    target_count = len(keywords)

    risk = classify(
        operation="add_keywords",
        params={"target_count": target_count},
    )
    payload = {
        "ad_group_id": ad_group_id,
        "keywords": keywords,
        "__target_count__": target_count,
        "__partial_failure__": True,
    }
    params_summary = _build_params_summary(ad_group_id, keywords)
    match_dist = params_summary["match_types_distribution"]
    summary = (
        f"Adicionar {target_count} KW(s) ao ad_group {ad_group_id}. "
        f"Match types: {', '.join(f'{mt}({n})' for mt, n in sorted(match_dist.items()))}."
    )

    if risk.level == RiskLevel.AUTO:
        result = await run_mutation(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="add_keywords",
            payload=payload,
            target_count=target_count,
            partial_failure=True,
            params_summary=params_summary,
        )
        partial_failures = result.get("partial_failures", [])
        added: list[dict[str, Any]] = []
        for idx, kw in enumerate(keywords):
            per_op = next((p for p in partial_failures if p["index"] == idx), None)
            row_status = classify_partial(
                per_op["error"] if per_op else None,
                ok_status="added",
                exists_status="already_exists",
                exists_patterns=_ALREADY_EXISTS_PATTERNS,
            )
            item: dict[str, Any] = {
                "text": kw["text"],
                "match_type": kw["match_type"].upper(),
                "status": row_status,
            }
            if per_op and per_op["error"] and row_status == "failed":
                item["error"] = per_op["error"]
            added.append(item)
        return {
            "status": "applied",
            "operation": "add_keywords",
            "customer_id": customer_id,
            "ad_group_id": ad_group_id,
            "blast_summary": summary,
            "applied_count": result["applied_count"],
            "provider_request_id": result["provider_request_id"],
            "auto_applied_reason": risk.reason,
            "added": added,
        }

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="add_keywords",
            payload=payload,
            blast_summary=summary,
        )
    return {
        "status": "dry_run",
        "operation": "add_keywords",
        "customer_id": customer_id,
        "ad_group_id": ad_group_id,
        "blast_summary": summary,
        "confirmation_token": token,
        "expires_in_minutes": 10,
        "to_apply": "Chame apply_change(confirmation_token=<token>) para aplicar.",
        "confirmation_reason": risk.reason,
    }
