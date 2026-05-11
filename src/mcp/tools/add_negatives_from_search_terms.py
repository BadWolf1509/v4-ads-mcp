"""Tool: add_negatives_from_search_terms - bulk add negatives derived from search_terms_report.

Workflow: gestor calls get_search_terms_report -> picks bad terms -> passes them
here with scope (campaign / ad_group / shared_set) for each. Auto-applies
(negatives are safe per spec §7.1). Up to 500 per call. Returns per-row status
including 'already_exists' for terms that were already negatives (idempotent).
"""

from collections import Counter
from typing import Any

from src.google_ads.mutations import run_mutation
from src.governance.blast_radius import classify
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "negatives": {
            "type": "array",
            "minItems": 1,
            "maxItems": 500,
            "items": {
                "type": "object",
                "properties": {
                    "search_term": {"type": "string", "minLength": 1, "maxLength": 80},
                    "match_type": {
                        "type": "string",
                        "enum": ["EXACT", "PHRASE", "BROAD"],
                        "default": "EXACT",
                    },
                    "scope": {
                        "type": "string",
                        "enum": ["campaign", "ad_group", "shared_set"],
                    },
                    "scope_id": {"type": "string", "pattern": "^[0-9]+$"},
                },
                "required": ["search_term", "scope", "scope_id"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["customer_id", "negatives"],
    "additionalProperties": False,
}


# Google Ads error codes that indicate the criterion already exists (idempotent case).
_ALREADY_EXISTS_PATTERNS = (
    "CRITERION_EXISTS",
    "DUPLICATE_KEYWORD",
)


def _build_params_summary(negatives: list[dict[str, Any]]) -> dict[str, Any]:
    """Audit-safe summary: aggregate metadata only, never the terms themselves (spec §3.5)."""
    scopes = Counter(n["scope"] for n in negatives)
    match_types = Counter(n.get("match_type", "EXACT") for n in negatives)
    scope_ids = {(n["scope"], n["scope_id"]) for n in negatives}
    return {
        "scopes_distribution": dict(scopes),
        "match_types_distribution": dict(match_types),
        "scope_ids_count": len(scope_ids),
    }


def _classify_partial(error: str | None) -> str:
    """Map a Google Ads partial-failure error message to per-row status."""
    if error is None:
        return "added"
    upper = error.upper()
    if any(p in upper for p in _ALREADY_EXISTS_PATTERNS):
        return "already_exists"
    return "failed"


@register_tool(
    name="add_negatives_from_search_terms",
    description=(
        "Adiciona negativas derivadas do search_terms_report em batch. Aceita "
        "ate 500 termos com scope campaign|ad_group|shared_set. Sempre auto-aplica "
        "(spec §7.1) — idempotente: termos ja existentes retornam status "
        "'already_exists' sem falha. Use apos get_search_terms_report pra picar "
        "termos performando mal e exclui-los do leilao."
    ),
    input_schema=_SCHEMA,
)
async def add_negatives_from_search_terms(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    negatives = args["negatives"]
    target_count = len(negatives)

    risk = classify(
        operation="add_negatives_from_search_terms",
        params={"target_count": target_count},
    )

    payload = {"negatives": negatives}
    params_summary = _build_params_summary(negatives)

    result = await run_mutation(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        operation_type="add_negatives_from_search_terms",
        payload=payload,
        target_count=target_count,
        partial_failure=True,
        params_summary=params_summary,
    )

    # Zip partial_failures back to input rows in order
    partial_failures = result.get("partial_failures", [])
    added: list[dict[str, Any]] = []
    for idx, n in enumerate(negatives):
        # Default: if SDK didn't return partial-failure info for this idx, mark added
        per_op = next((p for p in partial_failures if p["index"] == idx), None)
        row_status = _classify_partial(per_op["error"] if per_op else None)
        item: dict[str, Any] = {
            "search_term": n["search_term"],
            "match_type": n.get("match_type", "EXACT"),
            "scope": n["scope"],
            "scope_id": n["scope_id"],
            "status": row_status,
        }
        if per_op and per_op["error"] and row_status == "failed":
            item["error"] = per_op["error"]
        added.append(item)

    return {
        "status": "applied",
        "operation": "add_negatives_from_search_terms",
        "customer_id": customer_id,
        "applied_count": result["applied_count"],
        "google_request_id": result["google_request_id"],
        "auto_applied_reason": risk.reason,
        "added": added,
    }
