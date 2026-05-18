"""Tool: create_campaign — create 1 SEARCH campaign with budget + geo + PT language.

Always-CONFIRM (creates campaign — sensitive per spec §7.1). Chained mutation
pattern (Sprint 3b.19B established): N+M+2 ops em single MutateGoogleAdsRequest:
- 1 campaign_budget_operation
- 1 campaign_operation (references temp budget path)
- N campaign_criterion_operations (locations, references temp campaign path)
- 1 campaign_criterion_operation (PT language, references temp campaign path)

V4 invariants hardcoded (no schema fields):
- status = PAUSED on create
- advertising_channel_type = SEARCH (v0 only)
- network: Search Partners OFF, Display Network OFF
- currency = BRL (account-level inherit)
- language = Portuguese (`languageConstants/1014`) auto-added as criterion

Sprint 3b.24.
"""

from __future__ import annotations

from typing import Any

_BIDDING_STRATEGY_ENUM = [
    "MAXIMIZE_CONVERSIONS",
    "MAXIMIZE_CONVERSION_VALUE",
    "TARGET_CPA",
    "TARGET_ROAS",
    "MANUAL_CPC",
    "MAXIMIZE_CLICKS",
]

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "customer_id",
        "name",
        "bidding_strategy",
        "daily_budget_brl",
        "geo_targets",
    ],
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "name": {"type": "string", "minLength": 1, "maxLength": 256},
        "bidding_strategy": {
            "type": "object",
            "additionalProperties": False,
            "required": ["type"],
            "properties": {
                "type": {"type": "string", "enum": _BIDDING_STRATEGY_ENUM},
                "target_cpa_brl": {"type": "number", "minimum": 0.01},
                "target_roas": {"type": "number", "minimum": 0.01},
                "cpc_bid_ceiling_brl": {"type": "number", "minimum": 0.01},
                "enhanced_cpc": {"type": "boolean"},
            },
        },
        "daily_budget_brl": {"type": "number", "minimum": 1.0},
        "geo_targets": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {
                "type": "string",
                "pattern": "^geoTargetConstants/[0-9]+$",
            },
        },
        "start_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
        },
        "end_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
        },
    },
}


def _validate_payload_shape(args: dict[str, Any]) -> str | None:
    """Returns PT-BR error if bidding_strategy conditional fields are inconsistent
    OR dates are inverted; else None.

    Sprint 3b.19B.1 convention — runtime validation in lieu of JSON Schema
    composition keywords (oneOf/allOf/anyOf rejected by Anthropic API).
    """
    bs = args["bidding_strategy"]
    bs_type = bs["type"]

    # Required-conditional fields
    if bs_type == "TARGET_CPA" and "target_cpa_brl" not in bs:
        return "TARGET_CPA requer bidding_strategy.target_cpa_brl."
    if bs_type == "TARGET_ROAS" and "target_roas" not in bs:
        return "TARGET_ROAS requer bidding_strategy.target_roas."

    # Strategy-specific optional fields rejected on wrong strategy
    if "enhanced_cpc" in bs and bs_type != "MANUAL_CPC":
        return "enhanced_cpc so e valido com MANUAL_CPC."
    if "cpc_bid_ceiling_brl" in bs and bs_type != "MAXIMIZE_CLICKS":
        return "cpc_bid_ceiling_brl so e valido com MAXIMIZE_CLICKS."
    if "target_cpa_brl" in bs and bs_type not in ("TARGET_CPA", "MAXIMIZE_CONVERSIONS"):
        return "target_cpa_brl valido apenas para TARGET_CPA ou MAXIMIZE_CONVERSIONS (eCPC mode)."
    if "target_roas" in bs and bs_type not in ("TARGET_ROAS", "MAXIMIZE_CONVERSION_VALUE"):
        return "target_roas valido apenas para TARGET_ROAS ou MAXIMIZE_CONVERSION_VALUE."

    # Schedule validation
    start = args.get("start_date")
    end = args.get("end_date")
    if start and end and start > end:
        return f"start_date ({start}) posterior a end_date ({end})."

    return None
