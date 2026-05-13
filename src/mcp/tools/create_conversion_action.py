"""Tool: create_conversion_action - create 1-5 ConversionActions at customer level.

Always-CONFIRM (creates sensitive per spec §7.1; conversion tracking affects
ROAS attribution + Smart Bidding strategies). Pre-flight rejects duplicate
names via GAQL batch lookup. ConversionActions are customer-level (no parent
campaign/ad_group required).

V4 invariants:
- status: always ENABLED on create (gestor wants immediate activation)
- currency_code: hardcoded "BRL" (V4 = Brazil only)
- counting_type: defaults ONE_PER_CLICK when omitted

Out of scope v0:
- Tag generation/installation (WEBPAGE actions need manual gtag/GA4 setup
  via Google Ads UI > Tools > Conversions; or gestor reads back via
  get_conversion_actions to get tag_snippets server-generated)
- Offline conversion import (separate tool, Standard Access blocked)
- Attribution model + lookback window overrides (Google defaults; UI edit
  if needed)
- Status PAUSED on create + remove/update ConversionAction (future sprints)
- Niche categories (STORE_*, GET_DIRECTIONS, OUTBOUND_CLICK) + niche types
  (FIREBASE_*, FLOODLIGHT_*, etc) excluded from whitelist v0
"""

from collections import Counter
from typing import Any

from src.db import connection
from src.google_ads.queries._common import validate_conversion_action_create
from src.governance.blast_radius import classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_CATEGORY_ENUM = [
    "DEFAULT",
    "LEAD",
    "PURCHASE",
    "SIGNUP",
    "SUBMIT_LEAD_FORM",
    "BOOK_APPOINTMENT",
    "REQUEST_QUOTE",
    "PHONE_CALL_LEAD",
    "IMPORTED_LEAD",
    "QUALIFIED_LEAD",
    "CONVERTED_LEAD",
    "ADD_TO_CART",
    "BEGIN_CHECKOUT",
    "SUBSCRIBE_PAID",
    "DOWNLOAD",
    "CONTACT",
    "ENGAGEMENT",
    "PAGE_VIEW",
]

_TYPE_ENUM = ["WEBPAGE", "UPLOAD_CLICKS", "UPLOAD_CALLS"]

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["customer_id", "conversion_actions"],
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "conversion_actions": {
            "type": "array",
            "minItems": 1,
            "maxItems": 5,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "category", "type"],
                "properties": {
                    "name": {"type": "string", "minLength": 1, "maxLength": 100},
                    "category": {"type": "string", "enum": _CATEGORY_ENUM},
                    "type": {"type": "string", "enum": _TYPE_ENUM},
                    "counting_type": {
                        "type": "string",
                        "enum": ["ONE_PER_CLICK", "MANY_PER_CLICK"],
                    },
                    "value_settings": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "default_value_brl": {"type": "number", "minimum": 0},
                            "always_use_default_value": {"type": "boolean"},
                        },
                    },
                },
            },
        },
    },
}


def _build_params_summary(actions: list[dict[str, Any]]) -> dict[str, Any]:
    """Audit-safe: counts only, NO copy text per spec §3.6."""
    return {
        "count": len(actions),
        "categories": dict(Counter(a["category"] for a in actions)),
        "types": dict(Counter(a["type"] for a in actions)),
        "with_default_value": sum(
            1
            for a in actions
            if "value_settings" in a and "default_value_brl" in a["value_settings"]
        ),
        "with_always_use_default": sum(
            1
            for a in actions
            if "value_settings" in a and a["value_settings"].get("always_use_default_value")
        ),
    }


@register_tool(
    name="create_conversion_action",
    description=(
        "Cria 1-5 ConversionActions no nivel customer. Cada action: name "
        "(1-100 chars) + category + type. Always-CONFIRM. Categorias suportadas "
        "(18 V4-focused): LEAD, PURCHASE, SIGNUP, DEFAULT, SUBMIT_LEAD_FORM, "
        "BOOK_APPOINTMENT, REQUEST_QUOTE, PHONE_CALL_LEAD, IMPORTED_LEAD, "
        "QUALIFIED_LEAD, CONVERTED_LEAD, ADD_TO_CART, BEGIN_CHECKOUT, "
        "SUBSCRIBE_PAID, DOWNLOAD, CONTACT, ENGAGEMENT, PAGE_VIEW. Tipos: "
        "WEBPAGE (tag manual install fora do escopo MCP), UPLOAD_CLICKS "
        "(offline conversion import — Standard Access required pra usar), "
        "UPLOAD_CALLS (offline call import). Defaults: status=ENABLED, "
        "currency=BRL, counting_type=ONE_PER_CLICK. value_settings opcional "
        "com default_value_brl + always_use_default_value. Pre-flight rejeita "
        "nome duplicado (unico por customer). Para tag/import setup, use "
        "Google Ads UI ou tools especificas (sprints futuras)."
    ),
    input_schema=_SCHEMA,
)
async def create_conversion_action(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    actions = args["conversion_actions"]
    target_count = len(actions)

    error = await validate_conversion_action_create(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        actions=actions,
    )
    if error:
        return {
            "status": "error",
            "error": error,
            "operation": "create_conversion_action",
        }

    risk = classify(operation="create_conversion_action", params={"target_count": target_count})

    params_summary = _build_params_summary(actions)
    cat_dist = params_summary["categories"]
    type_dist = params_summary["types"]
    summary = (
        f"Criar {target_count} conversion_action(s): categorias {cat_dist}, tipos {type_dist}."
    )

    payload = {
        "conversion_actions": actions,
        "__target_count__": target_count,
        "__params_summary__": params_summary,
    }

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="create_conversion_action",
            payload=payload,
            blast_summary=summary,
        )

    preview = [
        {
            "name": a["name"],
            "category": a["category"],
            "type": a["type"],
            "counting_type": a.get("counting_type", "ONE_PER_CLICK"),
            "has_value_settings": "value_settings" in a,
        }
        for a in actions
    ]

    return {
        "status": "dry_run",
        "operation": "create_conversion_action",
        "customer_id": customer_id,
        "blast_summary": summary,
        "actions_preview": preview,
        "confirmation_token": token,
        "expires_in_minutes": 10,
        "to_apply": "Chame apply_change(confirmation_token=<token>) para aplicar.",
        "confirmation_reason": risk.reason,
    }
