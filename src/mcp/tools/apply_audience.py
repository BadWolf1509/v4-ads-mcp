# bucket: always
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

Sprint 3b.5 A4 constraint: user_list exclusion at campaign level is NOT
supported by Google Ads API (negative flag silently dropped). Use
target_type='ad_group' for user_list exclusion. user_interest exclusion
at campaign level works normally.

Idempotency (Sprint 3b.3 lesson): Google likely silent-dedupes duplicates;
defensive _classify_partial mapping for CRITERION_EXISTS / DUPLICATE_CRITERION
is kept but may not fire in practice.
"""

from collections import Counter
from typing import Any

from src.db import connection
from src.google_ads.mutations import run_mutation
from src.google_ads.reports import run_report
from src.governance.blast_radius import RiskLevel, classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._common import classify_partial
from src.mcp.tools._mutate_common import applied_envelope, error_envelope, preview_envelope
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

# A3 finding (Sprint 3b.4 smoke): Google silently drops user_interest attachments
# when taxonomy_type is incompatible with target_type. SEARCH ad_groups accept
# IN_MARKET + AFFINITY; VERTICAL_GEO (Display Topics, IDs 1-79999) silently dropped.
_COMPATIBLE_TAXONOMIES = ("IN_MARKET", "AFFINITY")


def _preflight_validate(
    customer_id: str, target_type: str, mode: str, attachments: list[dict[str, Any]]
) -> str | None:
    """Returns error message PT-BR if invalid; None if OK.

    Validations (spec §3.5 + Sprint 3b.5 §3.2):
    - A4 (NEW): campaign + exclusion + user_list combo (Google silent-overrides)
    - bid_modifier + exclusion incompatibility
    - audience_type vs resource_name path consistency
    - audience_resource_name customer_id consistency
    """
    # A4 finding (Sprint 3b.4 smoke + 3b.5 brainstorming empirical):
    # Google silently overrides negative=True → false on CampaignCriterion when
    # subtype is user_list. AdGroupCriterion honors it correctly. Direct gestor
    # to ad_group level for user_list exclusion.
    if target_type == "campaign" and mode == "exclusion":
        offending = [i for i, a in enumerate(attachments) if a["audience_type"] == "user_list"]
        if offending:
            return (
                f"Customer Match (user_list) exclusion em campaign level nao eh "
                f"suportada pela Google Ads API — negative flag eh silently dropado "
                f"em CampaignCriterion para user_list. Use target_type='ad_group' "
                f"em vez disso (attachments {offending} sao user_list). "
                f"user_interest exclusion em campaign continua funcionando."
            )

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


async def _validate_user_interest_taxonomies(
    ctx: Any, customer_id: str, attachments: list[dict[str, Any]]
) -> str | None:
    """Returns error message PT-BR if any user_interest taxonomy incompatible; None if OK.

    Performs 1 GAQL batch lookup if user_interest attachments present.
    Returns None (skip) if no user_interest in batch.

    Spec §3.3: SEARCH ad_groups/campaigns only accept IN_MARKET + AFFINITY
    taxonomies. VERTICAL_GEO (Display Topics, IDs 1-79999) is silently dropped
    by Google (A3 finding).
    """
    user_interest_ids: list[str] = []
    user_interest_indices: list[int] = []
    for i, att in enumerate(attachments):
        if att["audience_type"] == "user_interest":
            ui_id = att["audience_resource_name"].rsplit("/", 1)[-1]
            user_interest_ids.append(ui_id)
            user_interest_indices.append(i)

    if not user_interest_ids:
        return None  # No user_interest attachments; skip GAQL lookup

    ids_clause = ", ".join(user_interest_ids)
    query = (
        f"SELECT user_interest.user_interest_id, user_interest.taxonomy_type "
        f"FROM user_interest "
        f"WHERE user_interest.user_interest_id IN ({ids_clause})"
    )
    rows = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=lambda r: {
            "id": str(r.user_interest.user_interest_id),
            "taxonomy_type": r.user_interest.taxonomy_type.name,
        },
        operation_name="apply_audience_preflight_taxonomy_lookup",
        audit_this_call=False,  # internal read for validation, not user-facing audit
    )

    taxonomy_by_id = {row["id"]: row["taxonomy_type"] for row in rows}

    incompatible: list[dict[str, Any]] = []
    for i, ui_id in zip(user_interest_indices, user_interest_ids, strict=True):
        taxonomy = taxonomy_by_id.get(ui_id, "UNKNOWN")
        if taxonomy not in _COMPATIBLE_TAXONOMIES:
            incompatible.append({"index": i, "id": ui_id, "taxonomy": taxonomy})

    if incompatible:
        details = ", ".join(
            f"attachments[{x['index']}]={x['id']} ({x['taxonomy']})" for x in incompatible
        )
        return (
            f"user_interest attachments com taxonomy_type incompativel detectados: "
            f"{details}. Apenas {', '.join(_COMPATIBLE_TAXONOMIES)} sao aceitas pra "
            f"attachment em ad_group/campaign (V4 use case SEARCH). VERTICAL_GEO "
            f"(Display Topics, IDs 1-79999) eh silently dropado pelo Google."
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


@register_tool(
    name="apply_audience",
    description=(
        "[CORE] Anexa audience criteria (user_list ou user_interest) a 1+ ad_groups OU "
        "campaigns existentes. target_type top-level (ad_group|campaign) + mode "
        "top-level (observation|exclusion) + ate 100 attachments. "
        "Observation = positive attach (negative=False, bid_modifier opcional 0.1-10.0). "
        "Exclusion = negative=True (delivery exclusion, bid_modifier nao permitido). "
        "IMPORTANT: user_list exclusion em campaign nao funciona (Google silently drops "
        "negative flag) — use target_type='ad_group' pra Customer Match exclusion. "
        "user_interest exclusion em campaign funciona normalmente. "
        "Classification: observation ≤20 AUTO, >20 CONFIRM; exclusion sempre CONFIRM "
        "(delivery impact). Idempotente state-wise (Google deduplica server-side). "
        "Use com get_audience_performance pra ver attachments existentes + escolher "
        "user_list ou user_interest resource_names existentes."
    ),
    input_schema=_SCHEMA,
    bucket="always",
)
async def apply_audience(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    target_type = args["target_type"]
    mode = args["mode"]
    attachments = args["attachments"]
    target_count = len(attachments)

    # Pre-flight validation (schema can't express conditional rules)
    preflight_error = _preflight_validate(customer_id, target_type, mode, attachments)
    if preflight_error:
        return error_envelope("apply_audience", preflight_error, customer_id=customer_id)

    # A3: async pre-flight (GAQL taxonomy lookup) — only runs if sync passes + has user_interest
    taxonomy_error = await _validate_user_interest_taxonomies(ctx, customer_id, attachments)
    if taxonomy_error:
        return error_envelope("apply_audience", taxonomy_error, customer_id=customer_id)

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
            row_status = classify_partial(
                per_op["error"] if per_op else None,
                ok_status="attached",
                exists_status="already_attached",
                exists_patterns=_ALREADY_EXISTS_PATTERNS,
            )
            item: dict[str, Any] = {
                "target_id": att["target_id"],
                "audience_type": att["audience_type"],
                "audience_resource_name": att["audience_resource_name"],
                "status": row_status,
            }
            if per_op and per_op["error"] and row_status == "failed":
                item["error"] = per_op["error"]
            attachments_result.append(item)
        return applied_envelope(
            "apply_audience",
            customer_id,
            summary,
            applied_count=result["applied_count"],
            provider_request_id=result["provider_request_id"],
            auto_applied_reason=risk.reason,
            target_type=target_type,
            mode=mode,
            attachments_result=attachments_result,
        )

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="apply_audience",
            payload=payload,
            blast_summary=summary,
        )
    return preview_envelope(
        "apply_audience",
        customer_id,
        summary,
        token,
        confirmation_reason=risk.reason,
        target_type=target_type,
        mode=mode,
    )
