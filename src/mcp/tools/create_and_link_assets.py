"""Tool: create_and_link_assets — create N text-assets + link to scope in chained mutation.

Always-CONFIRM (creates assets — sensitive per spec §7.1). Chained mutation
pattern (Sprint 3b.19B established): 2N ops em single MutateGoogleAdsRequest:
- N asset_operation.create
- N {customer|campaign|ad_group}_asset_operation.create (refs temp asset paths)

V4 invariants hardcoded (no schema fields):
- country_code = "BR" (CALL)
- language_code = "pt" (PROMOTION)
- currency_code = "BRL" (PROMOTION.money_amount_off)

Sprint 3b.25.
"""

from __future__ import annotations

from typing import Any

_ASSET_TYPES = ["SITELINK", "CALLOUT", "STRUCTURED_SNIPPET", "CALL", "PROMOTION"]
_ATTACHMENT_LEVELS = ["CUSTOMER", "CAMPAIGN", "AD_GROUP"]
_STRUCTURED_SNIPPET_HEADERS = [
    "AMENITIES",
    "BRANDS",
    "COURSES",
    "DEGREE_PROGRAMS",
    "DESTINATIONS",
    "FEATURED_HOTELS",
    "INSURANCE_COVERAGE",
    "MODELS",
    "NEIGHBORHOODS",
    "SERVICE_CATALOG",
    "SHOWS",
    "STYLES",
    "TYPES",
]

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["customer_id", "assets"],
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "assets": {
            "type": "array",
            "minItems": 1,
            "maxItems": 20,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["type", "attachment_level", "attachment_id"],
                "properties": {
                    "type": {"type": "string", "enum": _ASSET_TYPES},
                    "attachment_level": {"type": "string", "enum": _ATTACHMENT_LEVELS},
                    "attachment_id": {"type": "string"},
                    "link_text": {"type": "string", "minLength": 1, "maxLength": 25},
                    "final_urls": {
                        "type": "array",
                        "items": {"type": "string", "format": "uri"},
                        "minItems": 1,
                        "maxItems": 5,
                    },
                    "description1": {"type": "string", "minLength": 1, "maxLength": 35},
                    "description2": {"type": "string", "minLength": 1, "maxLength": 35},
                    "callout_text": {"type": "string", "minLength": 1, "maxLength": 25},
                    "header": {"type": "string", "enum": _STRUCTURED_SNIPPET_HEADERS},
                    "values": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1, "maxLength": 25},
                        "minItems": 3,
                        "maxItems": 10,
                    },
                    "phone_number": {
                        "type": "string",
                        "pattern": r"^[\d\s\(\)\-]{10,20}$",
                    },
                    "promotion_target": {"type": "string", "minLength": 1, "maxLength": 20},
                    "discount_modifier": {"type": "string", "enum": ["NONE", "UP_TO"]},
                    "percent_off": {"type": "number", "minimum": 0.01, "maximum": 100.0},
                    "money_amount_off_brl": {"type": "number", "minimum": 0.01},
                    "start_date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
                    "end_date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
                },
            },
        },
    },
}


_PER_TYPE_REQUIRED = {
    "SITELINK": ["link_text", "final_urls"],
    "CALLOUT": ["callout_text"],
    "STRUCTURED_SNIPPET": ["header", "values"],
    "CALL": ["phone_number"],
    "PROMOTION": ["promotion_target", "discount_modifier", "final_urls"],
}

_PER_TYPE_ALLOWED: dict[str, set[str]] = {
    "SITELINK": {"link_text", "final_urls", "description1", "description2"},
    "CALLOUT": {"callout_text"},
    "STRUCTURED_SNIPPET": {"header", "values"},
    "CALL": {"phone_number"},
    "PROMOTION": {
        "promotion_target",
        "discount_modifier",
        "percent_off",
        "money_amount_off_brl",
        "final_urls",
        "start_date",
        "end_date",
    },
}

_COMMON_KEYS = {"type", "attachment_level", "attachment_id"}


def _err(idx: int, msg: str) -> dict[str, Any]:
    return {
        "status": "error",
        "error": f"assets[{idx}]: {msg}",
        "operation": "create_and_link_assets",
    }


def _validate_payload_shape(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Cross-field validation that JSONSchema cannot express (Sprint 3b.19B.1 convention).

    Returns None if valid, error dict if invalid.
    """
    customer_id = payload["customer_id"]

    for idx, a in enumerate(payload["assets"]):
        atype = a["type"]
        alevel = a["attachment_level"]
        aid = a["attachment_id"]

        # Check 1: attachment_id consistency with attachment_level
        if alevel == "CUSTOMER":
            if aid != customer_id:
                return _err(
                    idx,
                    f"attachment_id deve igualar customer_id ('{customer_id}') "
                    f"quando attachment_level=CUSTOMER",
                )
        elif alevel == "CAMPAIGN":
            expected_prefix = f"customers/{customer_id}/campaigns/"
            if not aid.startswith(expected_prefix):
                return _err(
                    idx,
                    f"attachment_id deve ser resource path '{expected_prefix}<id>' "
                    f"quando attachment_level=CAMPAIGN",
                )
        elif alevel == "AD_GROUP":
            expected_prefix = f"customers/{customer_id}/adGroups/"
            if not aid.startswith(expected_prefix):
                return _err(
                    idx,
                    f"attachment_id deve ser resource path '{expected_prefix}<id>' "
                    f"quando attachment_level=AD_GROUP",
                )

        # Check 2: per-type required fields
        for f in _PER_TYPE_REQUIRED[atype]:
            if f not in a:
                return _err(idx, f"campo '{f}' obrigatório quando type={atype}")

        # Check 3: per-type forbidden fields (defense-in-depth)
        for f in set(a.keys()) - _COMMON_KEYS:
            if f not in _PER_TYPE_ALLOWED[atype]:
                return _err(idx, f"campo '{f}' não aplicável a type={atype}")

        # Check 4: SITELINK description1/description2 paired
        if atype == "SITELINK":
            d1 = "description1" in a
            d2 = "description2" in a
            if d1 != d2:
                return _err(
                    idx,
                    "description1 e description2 devem ser ambos presentes ou ambos ausentes",
                )

        # Check 5: PROMOTION discount XOR
        if atype == "PROMOTION":
            has_pct = "percent_off" in a
            has_amt = "money_amount_off_brl" in a
            if has_pct == has_amt:
                return _err(
                    idx,
                    "PROMOTION requer exatamente um de 'percent_off' OU 'money_amount_off_brl'",
                )

            # Check 6: PROMOTION dates ordering
            if "start_date" in a and "end_date" in a and a["end_date"] < a["start_date"]:
                return _err(
                    idx,
                    f"end_date ({a['end_date']}) deve ser >= start_date ({a['start_date']})",
                )

    return None
