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

from src.db import connection
from src.governance.blast_radius import classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

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


def _build_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Audit-safe summary: counts only, NO copy text per spec §3.6.

    Returns dict with asset_count, by_type, by_level, attachment_ids_distinct,
    total_ops_chained.
    """
    by_type: dict[str, int] = {}
    by_level: dict[str, int] = {}
    distinct_ids: set[str] = set()
    for a in payload["assets"]:
        by_type[a["type"]] = by_type.get(a["type"], 0) + 1
        by_level[a["attachment_level"]] = by_level.get(a["attachment_level"], 0) + 1
        distinct_ids.add(a["attachment_id"])
    n = len(payload["assets"])
    return {
        "asset_count": n,
        "by_type": by_type,
        "by_level": by_level,
        "attachment_ids_distinct": len(distinct_ids),
        "total_ops_chained": 2 * n,
    }


@register_tool(
    name="create_and_link_assets",
    description=(
        "Cria N text-assets novos (1-20 por call) e linka cada um ao escopo "
        "solicitado (CUSTOMER/CAMPAIGN/AD_GROUP) em chained mutation atomic. "
        "Always-CONFIRM. Tipos suportados v0: SITELINK, CALLOUT, "
        "STRUCTURED_SNIPPET, CALL, PROMOTION (text-extension family, "
        "SEARCH-relevant). V4 invariants hardcoded: country_code=BR para CALL, "
        "language_code=pt para PROMOTION, currency_code=BRL para "
        "PROMOTION.money_amount_off. Cada item de `assets` carrega type + "
        "attachment_level + attachment_id + payload type-specific. Builder usa "
        "chained mutation (N CreateAssetOp + N Create{Customer,Campaign,"
        "AdGroup}AssetOp em single MutateGoogleAdsRequest com temp resource_names). "
        "F13 auto-retorna 2N resource_names. attachment_id formato: customer_id "
        "(CUSTOMER), 'customers/X/campaigns/Y' (CAMPAIGN), 'customers/X/adGroups/Y' "
        "(AD_GROUP). PROMOTION requer exatamente um de percent_off OU "
        "money_amount_off_brl."
    ),
    input_schema=_SCHEMA,
)
async def create_and_link_assets(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]

    # Runtime payload validation (Sprint 3b.19B.1 pattern).
    # IMPORTANT: _validate_payload_shape returns the FULL error dict
    # (NOT just a string like Sprint 3b.24 create_campaign).
    shape_error = _validate_payload_shape(args)
    if shape_error is not None:
        return shape_error  # already a full dict

    summary = _build_summary(args)
    target_count = summary["total_ops_chained"]

    risk = classify(
        operation="create_and_link_assets",
        params={"target_count": target_count},
    )

    blast_summary = (
        f"Criar {summary['asset_count']} asset(s) text-extension + "
        f"{summary['asset_count']} link(s). Tipos: "
        f"{', '.join(f'{k}:{v}' for k, v in summary['by_type'].items())}. "
        f"Níveis: {', '.join(f'{k}:{v}' for k, v in summary['by_level'].items())}."
    )

    payload = {
        **args,
        "__target_count__": target_count,
        "__params_summary__": summary,
    }

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="create_and_link_assets",
            payload=payload,
            blast_summary=blast_summary,
        )

    return {
        "status": "dry_run",
        "operation": "create_and_link_assets",
        "customer_id": customer_id,
        "blast_summary": blast_summary,
        "summary": summary,
        "confirmation_token": token,
        "expires_in_minutes": 10,
        "to_apply": "Chame apply_change(confirmation_token=<token>) para aplicar.",
        "confirmation_reason": risk.reason,
    }
