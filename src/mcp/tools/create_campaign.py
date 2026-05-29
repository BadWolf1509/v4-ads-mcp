# bucket: always
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

from src.db import connection
from src.google_ads.queries._common import validate_geo_target_constants_br_only
from src.governance.blast_radius import classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

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
                # enhanced_cpc REMOVED (F35, Sprint 3b.24.4): deprecated by Google,
                # rejected on Campaign create with OPERATION_NOT_PERMITTED_FOR_CONTEXT.
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
    # enhanced_cpc REMOVED (F35, Sprint 3b.24.4): deprecated; not in schema anymore.
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


def _build_params_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Audit-safe: counts only, NO copy text per spec §3.6."""
    bs = payload["bidding_strategy"]
    return {
        "bidding_strategy_type": bs["type"],
        "daily_budget_brl": payload["daily_budget_brl"],
        "geo_count": len(payload["geo_targets"]),
        "has_schedule": ("start_date" in payload) or ("end_date" in payload),
    }


@register_tool(
    name="create_campaign",
    description=(
        "[CORE] Cria 1 SEARCH campaign nova em uma conta V4. Always-CONFIRM. Schema "
        "requer name + bidding_strategy + daily_budget_brl + geo_targets (lista "
        "de geoTargetConstants resource paths, validados como BR via pre-flight "
        "V4). Status sempre PAUSED on create — gestor liga manualmente apos "
        "review. Language defaults Portuguese. Search Partners + Display Network "
        "OFF (V4 defaults). Bidding strategies suportadas v0: MAXIMIZE_CONVERSIONS, "
        "MAXIMIZE_CONVERSION_VALUE, TARGET_CPA (requer target_cpa_brl), "
        "TARGET_ROAS (requer target_roas), MANUAL_CPC, "
        "MAXIMIZE_CLICKS (opcional cpc_bid_ceiling_brl). Conversion goals "
        "inherit account-default (override fica pra v1). Channel SEARCH only v0 "
        "(PMAX/DISPLAY/SHOPPING v1). F13 resource_names auto-retorna paths "
        "criados (budget + campaign + N geo criterions + PT language criterion)."
    ),
    input_schema=_SCHEMA,
    bucket="always",
)
async def create_campaign(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]

    # Runtime payload validation (Sprint 3b.19B.1 pattern)
    shape_error = _validate_payload_shape(args)
    if shape_error:
        return {
            "status": "error",
            "error": shape_error,
            "operation": "create_campaign",
        }

    # Pre-flight: V4 BR-invariant geo validation
    error = await validate_geo_target_constants_br_only(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        geo_paths=args["geo_targets"],
    )
    if error:
        return {
            "status": "error",
            "error": error,
            "operation": "create_campaign",
        }

    # Compute target_count: 1 budget + 1 campaign + N geos + 1 language
    geo_count = len(args["geo_targets"])
    target_count = 2 + geo_count + 1

    risk = classify(
        operation="create_campaign",
        params={"target_count": target_count},
    )

    params_summary = _build_params_summary(args)
    bs = args["bidding_strategy"]

    summary = (
        f"Criar 1 campanha SEARCH (PAUSED) + budget BRL "
        f"{args['daily_budget_brl']:.2f}/dia + {geo_count} geo target(s) + "
        f"PT language. Bidding: {bs['type']}."
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
            operation_type="create_campaign",
            payload=payload,
            blast_summary=summary,
        )

    preview = {
        "name": args["name"],
        "bidding_strategy_type": bs["type"],
        "daily_budget_brl": args["daily_budget_brl"],
        "geo_count": geo_count,
        "has_schedule": params_summary["has_schedule"],
    }

    return {
        "status": "dry_run",
        "operation": "create_campaign",
        "customer_id": customer_id,
        "blast_summary": summary,
        "preview": preview,
        "confirmation_token": token,
        "expires_in_minutes": 10,
        "to_apply": "Chame apply_change(confirmation_token=<token>) para aplicar.",
        "confirmation_reason": risk.reason,
    }
