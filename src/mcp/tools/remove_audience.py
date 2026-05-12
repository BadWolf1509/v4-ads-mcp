"""Tool: remove_audience - detach audience criteria (user_list or user_interest)
previamente anexadas a 1 ad_group ou campaign.

Sprint 3b.6 (closes audience CRUD: 3b.4 create + 3b.5 validation + 3b.6 delete).

Always CONFIRM (spec §7.1 "Remove qualquer coisa = sempre confirma") — friction
trivial vs valor de prevenir accidental delivery restoration (exclusion removal
restaura audience à pool de delivery).

Per-row error mapping (defensive guard from Sprint 3b.3 A1 silent dedupe lesson):
- Sucesso (None) → "removed"
- RESOURCE_NOT_FOUND family → "already_removed" (idempotent retry safe)
- Outros → "failed"

Per-row visibility is at audit_log level only (apply_change não surface per-row
response — future enhancement if real demand).
"""

from typing import Any

from src.db import connection
from src.governance.blast_radius import classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "target_type": {"type": "string", "enum": ["ad_group", "campaign"]},
        "target_id": {"type": "string", "pattern": "^[0-9]+$"},
        "criterion_ids": {
            "type": "array",
            "items": {"type": "string", "pattern": "^[0-9]+$"},
            "minItems": 1,
            "maxItems": 100,
        },
    },
    "required": ["customer_id", "target_type", "target_id", "criterion_ids"],
    "additionalProperties": False,
}


# Defensive guard: Google may return NOT_FOUND error when removing already-removed
# criterion, OR may silently succeed. Mapping handles both cases for idempotent
# cleanup retries (Sprint 3b.3 A1 lesson on silent-vs-explicit handling).
_ALREADY_REMOVED_PATTERNS = (
    "RESOURCE_NOT_FOUND",
    "NOT_FOUND",
    "DOES_NOT_EXIST",
    "CRITERION_NOT_FOUND",
)


def _build_params_summary(target_type: str, target_id: str, criterion_count: int) -> dict[str, Any]:
    """Audit-safe summary: aggregate counts only.

    target_id included (numeric IDs carry no competitive signal). criterion_ids
    list NOT included (deterministic from existing audience attachments, no signal
    beyond count).
    """
    return {
        "target_type": target_type,
        "target_id": target_id,
        "criterion_count": criterion_count,
    }


def _classify_partial(error: str | None) -> str:
    """Map a Google Ads partial-failure error to per-row status."""
    if error is None:
        return "removed"
    upper = error.upper()
    if any(p in upper for p in _ALREADY_REMOVED_PATTERNS):
        return "already_removed"
    return "failed"


@register_tool(
    name="remove_audience",
    description=(
        "Remove audience criteria (user_list ou user_interest) previamente anexadas "
        "a 1 ad_group ou campaign. Aceita target_type (ad_group|campaign) + "
        "target_id singular + criterion_ids array com ate 100 criteria do mesmo "
        "target. Sempre CONFIRM (spec §7.1 remove). Idempotente: criteria ja "
        "removidas retornam graciosamente via partial_failure mode (audit_log mostra "
        "'already_removed' per-row). Pega criterion_id da response de "
        "get_audience_performance ou Google Ads UI."
    ),
    input_schema=_SCHEMA,
)
async def remove_audience(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    target_type = args["target_type"]
    target_id = args["target_id"]
    criterion_ids = args["criterion_ids"]
    target_count = len(criterion_ids)

    # No pre-flight validation needed (criterion_ids são digit strings — partial_failure
    # handles missing criteria graciously via _classify_partial mapping)

    risk = classify(operation="remove_audience", params={"target_count": target_count})
    # Always CONFIRM path — no AUTO branch

    payload = {
        "target_type": target_type,
        "target_id": target_id,
        "criterion_ids": criterion_ids,
        "__target_count__": target_count,
        "__partial_failure__": True,
        "__params_summary__": _build_params_summary(target_type, target_id, target_count),
    }
    summary = f"Remover {target_count} audience criteria do {target_type} {target_id}."

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="remove_audience",
            payload=payload,
            blast_summary=summary,
        )
    return {
        "status": "dry_run",
        "operation": "remove_audience",
        "customer_id": customer_id,
        "target_type": target_type,
        "target_id": target_id,
        "blast_summary": summary,
        "confirmation_token": token,
        "expires_in_minutes": 10,
        "to_apply": "Chame apply_change(confirmation_token=<token>) para aplicar.",
        "confirmation_reason": risk.reason,
    }
