# bucket: defer
"""Tool: create_conversion_value_rule_set - create 1 RuleSet with 1-10 rules nested.

Always-CONFIRM (creates sensitive per spec §7.1; rules affect ROAS attribution
via conditional value boost). Chained mutation: N rule operations + 1 RuleSet
operation em single MutateGoogleAdsRequest.

V4 invariants:
- status: always ENABLED on create
- geo targets validated as BR-only via pre-flight
- attachment to CUSTOMER (account-wide) or CAMPAIGN (campaign-scoped)

Out of scope v0:
- AUDIENCE / ITINERARY condition types (sprints futuras)
- update/remove RuleSet
- ConversionValueRule standalone create (useless without RuleSet)
- Geo target SUGGESTION helper (gestor passa resource paths)
"""

from collections import Counter
from typing import Any

from src.db import connection
from src.google_ads.queries._common import (
    validate_campaign_for_value_rule_set,
    validate_geo_target_constants_br_only,
)
from src.governance.blast_radius import classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._mutate_common import error_envelope, preview_envelope
from src.mcp.tools._registry import register_tool

# Sprint 3b.22 (F25+F27 cleanup): removed _CATEGORY_ENUM (conversion_action_categories
# Google API only accepts [] / [STORE_VISIT] / [STORE_SALE], the 13-cat whitelist
# herdada de 3b.19A é invalida pra esse campo — STORE out of scope v0).
# Removed NO_CONDITION from condition_type enum (Google rejects para non-Store
# RuleSets: "Dimension NO_CONDITION can only be used by Store Visits/Store Sales
# value rule set.").
_OPERATION_ENUM = ["ADD", "MULTIPLY", "SET"]
_CONDITION_TYPE_ENUM = ["DEVICE", "GEO_LOCATION"]
_DEVICE_TYPE_ENUM = ["MOBILE", "DESKTOP", "TABLET"]
_GEO_MATCH_TYPE_ENUM = ["ANY", "LOCATION_OF_PRESENCE"]
_ATTACHMENT_TYPE_ENUM = ["CUSTOMER", "CAMPAIGN"]

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["customer_id", "attachment_type", "rules"],
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "attachment_type": {"type": "string", "enum": _ATTACHMENT_TYPE_ENUM},
        "campaign_id": {"type": "string", "pattern": "^[0-9]+$"},
        "rules": {
            "type": "array",
            "minItems": 1,
            "maxItems": 10,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["action", "condition_type"],
                "properties": {
                    "action": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["operation", "value"],
                        "properties": {
                            "operation": {"type": "string", "enum": _OPERATION_ENUM},
                            "value": {"type": "number", "minimum": 0},
                        },
                    },
                    "condition_type": {"type": "string", "enum": _CONDITION_TYPE_ENUM},
                    "device_condition": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["device_types"],
                        "properties": {
                            "device_types": {
                                "type": "array",
                                "minItems": 1,
                                "uniqueItems": True,
                                "items": {"type": "string", "enum": _DEVICE_TYPE_ENUM},
                            },
                        },
                    },
                    "geo_condition": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["geo_target_constants"],
                        "properties": {
                            "geo_target_constants": {
                                "type": "array",
                                "minItems": 1,
                                "uniqueItems": True,
                                "items": {
                                    "type": "string",
                                    "pattern": "^geoTargetConstants/[0-9]+$",
                                },
                            },
                            "geo_match_type": {
                                "type": "string",
                                "enum": _GEO_MATCH_TYPE_ENUM,
                            },
                        },
                    },
                },
            },
        },
    },
}


def _validate_payload_shape(args: dict[str, Any]) -> str | None:
    """Returns PT-BR error if conditional shape rules violated; else None.

    Replaces schema-level allOf+if/then (rejected by Anthropic API — see
    Sprint 3b.19B.1). Enforces:
    - attachment_type=CAMPAIGN requires campaign_id
    - condition_type=DEVICE requires device_condition
    - condition_type=GEO_LOCATION requires geo_condition
    """
    if args["attachment_type"] == "CAMPAIGN" and "campaign_id" not in args:
        return (
            "attachment_type=CAMPAIGN requer campaign_id no payload. "
            "Use CUSTOMER para anexar ao customer inteiro, ou forneca "
            "campaign_id."
        )
    for i, rule in enumerate(args["rules"]):
        ctype = rule["condition_type"]
        if ctype == "DEVICE" and "device_condition" not in rule:
            return (
                f"rules[{i}] tem condition_type=DEVICE mas falta device_condition. "
                f"Forneca device_condition.device_types."
            )
        if ctype == "GEO_LOCATION" and "geo_condition" not in rule:
            return (
                f"rules[{i}] tem condition_type=GEO_LOCATION mas falta geo_condition. "
                f"Forneca geo_condition.geo_target_constants."
            )
    return None


def _build_params_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Audit-safe: counts only, NO copy text per spec §3.6."""
    rules = payload["rules"]
    return {
        "rule_count": len(rules),
        "attachment_type": payload["attachment_type"],
        "campaign_scoped": payload["attachment_type"] == "CAMPAIGN",
        "operations": dict(Counter(r["action"]["operation"] for r in rules)),
        "condition_types": dict(Counter(r["condition_type"] for r in rules)),
    }


@register_tool(
    name="create_conversion_value_rule_set",
    description=(
        "[DEFER] Cria 1 ConversionValueRuleSet (customer-level ou campaign-level) com "
        "1-10 ConversionValueRule(s) nested. Always-CONFIRM. Rules condicionais "
        "ajustam o valor de conversao por device (MOBILE/DESKTOP/TABLET) ou geo "
        "(geo_target_constants resource paths). Action operations: ADD (soma "
        "valor fixo), MULTIPLY (multiplica), SET (sobrescreve). "
        "attachment_type=CAMPAIGN requer campaign_id; CUSTOMER aplica conta "
        "inteira (Google limita 1 RuleSet CUSTOMER-level por conta — sprint 3b.19B "
        "F26). v0 NAO suporta AUDIENCE/ITINERARY conditions nem categorias filter "
        "(Google API restringe filter a STORE_VISIT/STORE_SALE — out of scope v0). "
        "Geo targets validados como BR-only (V4 invariant)."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def create_conversion_value_rule_set(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    attachment_type = args["attachment_type"]
    rules = args["rules"]
    target_count = len(rules) + 1  # N rules + 1 set

    shape_error = _validate_payload_shape(args)
    if shape_error:
        return error_envelope("create_conversion_value_rule_set", shape_error)

    # Pre-flight 1: campaign (if CAMPAIGN attachment)
    if attachment_type == "CAMPAIGN":
        error = await validate_campaign_for_value_rule_set(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            campaign_id=args["campaign_id"],
        )
        if error:
            return error_envelope("create_conversion_value_rule_set", error)

    # Pre-flight 2: geo targets (if any GEO_LOCATION rules)
    geo_paths: list[str] = []
    for rule in rules:
        if rule["condition_type"] == "GEO_LOCATION":
            geo_paths.extend(rule["geo_condition"]["geo_target_constants"])

    if geo_paths:
        # Deduplicate while preserving order
        seen: set[str] = set()
        deduped: list[str] = []
        for p in geo_paths:
            if p not in seen:
                seen.add(p)
                deduped.append(p)

        error = await validate_geo_target_constants_br_only(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            geo_paths=deduped,
        )
        if error:
            return error_envelope("create_conversion_value_rule_set", error)

    risk = classify(
        operation="create_conversion_value_rule_set",
        params={"target_count": target_count},
    )

    params_summary = _build_params_summary(args)
    op_dist = params_summary["operations"]
    cond_dist = params_summary["condition_types"]
    summary = (
        f"Criar 1 RuleSet ({attachment_type}) com {len(rules)} rule(s): "
        f"operations {op_dist}, conditions {cond_dist}."
    )

    payload = {
        **args,
        "__target_count__": target_count,
        "__params_summary__": params_summary,
    }

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="create_conversion_value_rule_set",
            payload=payload,
            blast_summary=summary,
        )

    preview = {
        "attachment_type": attachment_type,
        "rule_count": len(rules),
        "operations": list(op_dist.keys()),
        "condition_types": list(cond_dist.keys()),
    }

    return preview_envelope(
        "create_conversion_value_rule_set",
        customer_id,
        summary,
        token,
        confirmation_reason=risk.reason,
        preview=preview,
    )
