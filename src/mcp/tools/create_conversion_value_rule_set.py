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
    validate_geo_target_constants_for_value_rule,
)
from src.governance.blast_radius import classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

# Reuse 3b.19A 13-value V4-focused whitelist
_CATEGORY_ENUM = [
    "DEFAULT",
    "PURCHASE",
    "SIGNUP",
    "SUBMIT_LEAD_FORM",
    "BOOK_APPOINTMENT",
    "REQUEST_QUOTE",
    "PHONE_CALL_LEAD",
    "ADD_TO_CART",
    "BEGIN_CHECKOUT",
    "SUBSCRIBE_PAID",
    "CONTACT",
    "ENGAGEMENT",
    "PAGE_VIEW",
]

_OPERATION_ENUM = ["ADD", "MULTIPLY", "SET"]
_CONDITION_TYPE_ENUM = ["DEVICE", "GEO_LOCATION", "NO_CONDITION"]
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
        "conversion_action_categories": {
            "type": "array",
            "items": {"type": "string", "enum": _CATEGORY_ENUM},
            "uniqueItems": True,
        },
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
    "allOf": [
        {
            "if": {"properties": {"attachment_type": {"const": "CAMPAIGN"}}},
            "then": {"required": ["campaign_id"]},
        }
    ],
}


def _build_params_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Audit-safe: counts only, NO copy text per spec §3.6."""
    rules = payload["rules"]
    return {
        "rule_count": len(rules),
        "attachment_type": payload["attachment_type"],
        "campaign_scoped": payload["attachment_type"] == "CAMPAIGN",
        "operations": dict(Counter(r["action"]["operation"] for r in rules)),
        "condition_types": dict(Counter(r["condition_type"] for r in rules)),
        "with_category_filter": bool(payload.get("conversion_action_categories")),
        "category_filter_count": len(payload.get("conversion_action_categories") or []),
    }


@register_tool(
    name="create_conversion_value_rule_set",
    description=(
        "Cria 1 ConversionValueRuleSet (customer-level ou campaign-level) com "
        "1-10 ConversionValueRule(s) nested. Always-CONFIRM. Rules condicionais "
        "ajustam o valor de conversao por device (MOBILE/DESKTOP/TABLET) ou geo "
        "(geo_target_constants resource paths). Action operations: ADD (soma "
        "valor fixo), MULTIPLY (multiplica), SET (sobrescreve). Optional "
        "conversion_action_categories filter (13 V4-focused categories da 3b.19A). "
        "attachment_type=CAMPAIGN requer campaign_id; CUSTOMER aplica conta "
        "inteira. NO_CONDITION rule e fallback default. v0 NAO suporta "
        "AUDIENCE/ITINERARY conditions. Geo targets validados como BR-only "
        "(V4 invariant)."
    ),
    input_schema=_SCHEMA,
)
async def create_conversion_value_rule_set(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    attachment_type = args["attachment_type"]
    rules = args["rules"]
    target_count = len(rules) + 1  # N rules + 1 set

    # Pre-flight 1: campaign (if CAMPAIGN attachment)
    if attachment_type == "CAMPAIGN":
        error = await validate_campaign_for_value_rule_set(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            campaign_id=args["campaign_id"],
        )
        if error:
            return {
                "status": "error",
                "error": error,
                "operation": "create_conversion_value_rule_set",
            }

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

        error = await validate_geo_target_constants_for_value_rule(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            geo_paths=deduped,
        )
        if error:
            return {
                "status": "error",
                "error": error,
                "operation": "create_conversion_value_rule_set",
            }

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
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="create_conversion_value_rule_set",
            payload=payload,
            blast_summary=summary,
        )

    preview = {
        "attachment_type": attachment_type,
        "rule_count": len(rules),
        "has_category_filter": params_summary["with_category_filter"],
        "operations": list(op_dist.keys()),
        "condition_types": list(cond_dist.keys()),
    }

    return {
        "status": "dry_run",
        "operation": "create_conversion_value_rule_set",
        "customer_id": customer_id,
        "blast_summary": summary,
        "preview": preview,
        "confirmation_token": token,
        "expires_in_minutes": 10,
        "to_apply": "Chame apply_change(confirmation_token=<token>) para aplicar.",
        "confirmation_reason": risk.reason,
    }
