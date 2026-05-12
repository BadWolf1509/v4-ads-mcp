"""Tool: apply_audience - attach user_list or user_interest audience criteria
to existing ad_group or campaign.

Supports 2 modes:
- observation: positive attachment (negative=False). bid_modifier optional
  (range 0.1-10.0); default behavior if absent = inherit (Google sets 1.0).
- exclusion: negative attachment (negative=True). bid_modifier NOT allowed
  (semanticamente N/A — exclusion blocks delivery entirely).

Audience types: user_list (Customer Match + Remarketing) or user_interest
(in-market + affinity). Resource names must belong to the same customer_id.

Classification: observation ≤20 attachments AUTO; observation >20 OR any
exclusion → CONFIRM (delivery impact policy, matches Sprint 3b.2 REMOVED).

Up to 100 attachments per call (cap conservative — audience attachments are
deliberate ops vs keyword adds).

Idempotency (Sprint 3b.3 lesson): Google likely silent-dedupes duplicates;
defensive _classify_partial mapping for CRITERION_EXISTS / DUPLICATE_CRITERION
is kept but may not fire in practice.
"""

from collections import Counter
from typing import Any

from src.db import connection
from src.google_ads.mutations import run_mutation
from src.governance.blast_radius import RiskLevel, classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "target_type": {"type": "string", "enum": ["ad_group", "campaign"]},
        "mode": {"type": "string", "enum": ["observation", "exclusion"]},
        "attachments": {
            "type": "array",
            "minItems": 1,
            "maxItems": 100,
            "items": {
                "type": "object",
                "properties": {
                    "target_id": {"type": "string", "pattern": "^[0-9]+$"},
                    "audience_type": {
                        "type": "string",
                        "enum": ["user_list", "user_interest"],
                    },
                    "audience_resource_name": {
                        "type": "string",
                        "pattern": "^customers/[0-9]{10}/(userLists|userInterests)/[0-9]+$",
                    },
                    "bid_modifier": {"type": "number", "minimum": 0.1, "maximum": 10.0},
                },
                "required": ["target_id", "audience_type", "audience_resource_name"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["customer_id", "target_type", "mode", "attachments"],
    "additionalProperties": False,
}


# Google Ads error codes that indicate the criterion already exists (defensive guard).
_ALREADY_EXISTS_PATTERNS = (
    "CRITERION_EXISTS",
    "DUPLICATE_CRITERION",
)


def _preflight_validate(
    customer_id: str, mode: str, attachments: list[dict[str, Any]]
) -> str | None:
    """Returns error message PT-BR if invalid; None if OK.

    Validations (spec §3.5 #7-9):
    - bid_modifier + exclusion incompatibility
    - audience_type vs resource_name path consistency
    - audience_resource_name customer_id consistency
    """
    if mode == "exclusion":
        offending = [i for i, a in enumerate(attachments) if "bid_modifier" in a]
        if offending:
            return (
                f"bid_modifier nao eh permitido em mode=exclusion "
                f"(attachments {offending} invalido(s) — exclusion bloqueia delivery, "
                f"bid_modifier eh semanticamente N/A)"
            )

    for i, att in enumerate(attachments):
        expected_segment = "userLists" if att["audience_type"] == "user_list" else "userInterests"
        if f"/{expected_segment}/" not in att["audience_resource_name"]:
            return (
                f"attachments[{i}]: audience_type='{att['audience_type']}' "
                f"incompativel com resource_name (esperado segmento /{expected_segment}/ "
                f"no path)"
            )

        if not att["audience_resource_name"].startswith(f"customers/{customer_id}/"):
            return (
                f"attachments[{i}]: resource_name pertence a outra conta "
                f"(esperado prefixo customers/{customer_id}/, recebido "
                f"'{att['audience_resource_name']}')"
            )

    return None


def _build_params_summary(
    target_type: str, mode: str, attachments: list[dict[str, Any]]
) -> dict[str, Any]:
    """Audit-safe summary: aggregate metadata only — never raw resource_names (spec §3.6)."""
    audience_types = Counter(a["audience_type"] for a in attachments)
    with_bid_modifier = sum(1 for a in attachments if "bid_modifier" in a)
    unique_targets = len({a["target_id"] for a in attachments})
    return {
        "target_type": target_type,
        "mode": mode,
        "audience_types_distribution": dict(audience_types),
        "with_bid_modifier_count": with_bid_modifier,
        "unique_targets_count": unique_targets,
    }


def _classify_partial(error: str | None) -> str:
    """Map a Google Ads partial-failure error message to per-row status."""
    if error is None:
        return "attached"
    upper = error.upper()
    if any(p in upper for p in _ALREADY_EXISTS_PATTERNS):
        return "already_attached"
    return "failed"


@register_tool(
    name="apply_audience",
    description=(
        "Anexa audience criteria (user_list ou user_interest) a 1+ ad_groups OU "
        "campaigns existentes. target_type top-level (ad_group|campaign) + mode "
        "top-level (observation|exclusion) + ate 100 attachments. "
        "Observation = positive attach (negative=False, bid_modifier opcional 0.1-10.0). "
        "Exclusion = negative=True (delivery exclusion, bid_modifier nao permitido). "
        "Classification: observation ≤20 AUTO, >20 CONFIRM; exclusion sempre CONFIRM "
        "(delivery impact). Idempotente state-wise (Google deduplica server-side). "
        "Use com get_audience_performance pra ver attachments existentes + escolher "
        "user_list ou user_interest resource_names existentes."
    ),
    input_schema=_SCHEMA,
)
async def apply_audience(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    target_type = args["target_type"]
    mode = args["mode"]
    attachments = args["attachments"]
    target_count = len(attachments)

    # Pre-flight validation (schema can't express conditional rules)
    preflight_error = _preflight_validate(customer_id, mode, attachments)
    if preflight_error:
        return {
            "status": "error",
            "operation": "apply_audience",
            "customer_id": customer_id,
            "error": preflight_error,
        }

    risk = classify(
        operation="apply_audience",
        params={"target_count": target_count, "mode": mode},
    )

    payload = {
        "target_type": target_type,
        "mode": mode,
        "attachments": attachments,
        "__target_count__": target_count,
        "__partial_failure__": True,
    }
    params_summary = _build_params_summary(target_type, mode, attachments)
    audience_dist = params_summary["audience_types_distribution"]
    dist_label = " ".join(f"{at}:{n}" for at, n in sorted(audience_dist.items()))
    summary = (
        f"Apply {target_count} audience(s) [{dist_label}] como {mode} "
        f"em {params_summary['unique_targets_count']} {target_type}(s)."
    )

    if risk.level == RiskLevel.AUTO:
        result = await run_mutation(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="apply_audience",
            payload=payload,
            target_count=target_count,
            partial_failure=True,
            params_summary=params_summary,
        )
        partial_failures = result.get("partial_failures", [])
        attachments_result: list[dict[str, Any]] = []
        for idx, att in enumerate(attachments):
            per_op = next((p for p in partial_failures if p["index"] == idx), None)
            row_status = _classify_partial(per_op["error"] if per_op else None)
            item: dict[str, Any] = {
                "target_id": att["target_id"],
                "audience_type": att["audience_type"],
                "audience_resource_name": att["audience_resource_name"],
                "status": row_status,
            }
            if per_op and per_op["error"] and row_status == "failed":
                item["error"] = per_op["error"]
            attachments_result.append(item)
        return {
            "status": "applied",
            "operation": "apply_audience",
            "customer_id": customer_id,
            "target_type": target_type,
            "mode": mode,
            "blast_summary": summary,
            "applied_count": result["applied_count"],
            "google_request_id": result["google_request_id"],
            "auto_applied_reason": risk.reason,
            "attachments_result": attachments_result,
        }

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="apply_audience",
            payload=payload,
            blast_summary=summary,
        )
    return {
        "status": "dry_run",
        "operation": "apply_audience",
        "customer_id": customer_id,
        "target_type": target_type,
        "mode": mode,
        "blast_summary": summary,
        "confirmation_token": token,
        "expires_in_minutes": 10,
        "to_apply": "Chame apply_change(confirmation_token=<token>) para aplicar.",
        "confirmation_reason": risk.reason,
    }
