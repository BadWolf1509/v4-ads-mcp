"""Tool: update_conversion_action — update name, primary_for_goal.

Sprint 3b.27. V0 minimal: 2 fields mutáveis (todos opcionais — incluir ao menos 1).
Field mask dinâmico por item via builder.

Pre-flight async: validate_conversion_actions_exist (each ID exists + not REMOVED).
Layer 2 sync: _validate_payload_shape (item tem ≥1 field mutável; sem duplicate IDs).

**F44 (Sprint 3b.27.1):** `include_in_conversions_metric` REMOVIDO do schema V0 — Google
runtime rejeita com "The field attempted to be mutated is immutable" em
ConversionAction.update v24, mesmo que SDK descriptor aceite. Família Silent-acceptance.
Descoberto em smoke T7 2026-05-20. Pra desligar conv metric tracking, use Google Ads UI.
"""

from typing import Any

from src.db import connection
from src.google_ads.mutations import run_mutation
from src.google_ads.queries._common import validate_conversion_actions_exist
from src.governance.blast_radius import RiskLevel, classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_MUTABLE_FIELDS = ("name", "primary_for_goal")

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "updates": {
            "type": "array",
            "minItems": 1,
            "maxItems": 50,
            "items": {
                "type": "object",
                "properties": {
                    "conversion_action_id": {"type": "string", "pattern": "^[0-9]+$"},
                    "name": {"type": "string", "minLength": 1, "maxLength": 100},
                    "primary_for_goal": {"type": "boolean"},
                },
                "required": ["conversion_action_id"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["customer_id", "updates"],
    "additionalProperties": False,
}


def _validate_payload_shape(args: dict[str, Any]) -> str | None:
    """Layer 2: synchronous validation pre-Google call.

    Rejects:
    - Item without any mutable field (just conversion_action_id)
    - Duplicate conversion_action_id in batch
    """
    updates = args["updates"]

    for idx, item in enumerate(updates):
        has_mutable = any(f in item for f in _MUTABLE_FIELDS)
        if not has_mutable:
            return (
                f"update item {idx} (conversion_action_id={item['conversion_action_id']}) "
                f"só tem conversion_action_id sem nenhum field mutável "
                f"({', '.join(_MUTABLE_FIELDS)}). Inclua ao menos 1 field pra atualizar."
            )

    seen: set[str] = set()
    duplicates: list[str] = []
    for item in updates:
        cid = item["conversion_action_id"]
        if cid in seen and cid not in duplicates:
            duplicates.append(cid)
        seen.add(cid)

    if duplicates:
        return (
            f"conversion_action_ids duplicados no batch: {duplicates}. "
            f"Cada ID deve aparecer no máximo 1 vez."
        )

    return None


@register_tool(
    name="update_conversion_action",
    description=(
        "Atualiza ConversionAction: name, primary_for_goal (off = action vira "
        "non-biddable em todas as campaigns). 2 fields V0 — todos opcionais por "
        "item (forneça ao menos 1). Single item rename auto-aplica. Batch > 1 "
        "OU primary_for_goal=False retorna preview dry-run com "
        "`confirmation_token` (UUID string, expires em 10 min). Fluxo: 1) chame "
        "esta tool -> recebe response com status='dry_run' + confirmation_token. "
        "2) revise `changes` (lista de fields_updated por ID). 3) chame "
        "`apply_change(confirmation_token=<token>)` pra executar. Pra desligar "
        "include_in_conversions_metric, use Google Ads UI (Google v24 marca o "
        "field como immutable — F44)."
    ),
    input_schema=_SCHEMA,
)
async def update_conversion_action(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    updates = args["updates"]

    # Layer 2: synchronous validation pre-Google
    shape_error = _validate_payload_shape(args)
    if shape_error:
        return {
            "status": "error",
            "operation": "update_conversion_action",
            "customer_id": customer_id,
            "error": shape_error,
        }

    # Layer 3: async pre-flight (validate IDs exist + not REMOVED)
    conversion_action_ids = [u["conversion_action_id"] for u in updates]
    preflight_error = await validate_conversion_actions_exist(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        conversion_action_ids=conversion_action_ids,
    )
    if preflight_error:
        return {
            "status": "error",
            "operation": "update_conversion_action",
            "customer_id": customer_id,
            **preflight_error,
        }

    target_count = len(updates)
    risk = classify(operation="update_conversion_action", params={"updates": updates})

    payload = {"updates": updates, "__target_count__": target_count}

    changes_preview = [
        {
            "conversion_action_id": u["conversion_action_id"],
            "fields_updated": [f for f in _MUTABLE_FIELDS if f in u],
        }
        for u in updates
    ]
    summary = f"Atualizar {target_count} ConversionAction(s)."

    if risk.level == RiskLevel.AUTO:
        result = await run_mutation(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="update_conversion_action",
            payload=payload,
            target_count=target_count,
        )
        return {
            "status": "applied",
            "operation": "update_conversion_action",
            "customer_id": customer_id,
            "blast_summary": summary,
            "changes": changes_preview,
            "applied_count": result["applied_count"],
            "google_request_id": result["google_request_id"],
            "auto_applied_reason": risk.reason,
        }

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="update_conversion_action",
            payload=payload,
            blast_summary=summary,
        )
    return {
        "status": "dry_run",
        "operation": "update_conversion_action",
        "customer_id": customer_id,
        "blast_summary": summary,
        "changes": changes_preview,
        "confirmation_token": token,
        "expires_in_minutes": 10,
        "to_apply": "Chame apply_change(confirmation_token=<token>) para aplicar.",
        "confirmation_reason": risk.reason,
    }
