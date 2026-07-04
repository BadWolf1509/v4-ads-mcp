# bucket: defer
"""Tool: update_rsa - modify existing Responsive Search Ads.

Always-CONFIRM. Updates via AdService.mutate_ads (not AdGroupAdService).
Provided field lists REPLACE existing (proto-plus semantics with
field_mask).

Pre-flight validates ad existence + RSA type + parent ad_group/campaign
context. Same JSONSchema rules as create_rsa for individual fields
(headlines 3-15 x 30 chars, etc) but all mutable fields optional. The
"at least one mutable field per update" constraint is enforced at runtime
in the tool body (Sprint 3b.19B.1: top-level anyOf is rejected by the
Anthropic Messages API; schema can't express it declaratively).
"""

from collections import Counter
from typing import Any

from src.db import connection
from src.google_ads.queries._common import validate_existing_rsas_for_update
from src.governance.blast_radius import classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._mutate_common import error_envelope, preview_envelope
from src.mcp.tools._registry import register_tool

_MUTABLE_FIELDS = ("headlines", "descriptions", "final_urls", "path1", "path2")


def _validate_updates_have_mutable_field(
    updates: list[dict[str, Any]],
) -> str | None:
    """Returns PT-BR error if any update lacks all mutable fields; else None.

    Replaces schema-level anyOf (rejected by Anthropic API — see Sprint
    3b.19B.1). First-found-offender semantics mirror Sprint 3b.5 pre-flight
    pattern for consistent UX.
    """
    for u in updates:
        if not any(f in u for f in _MUTABLE_FIELDS):
            fields = ", ".join(_MUTABLE_FIELDS)
            return (
                f"Update do ad_id {u['ad_id']} sem nenhum campo mutavel. "
                f"Forneca ao menos um de: {fields}."
            )
    return None


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "updates": {
            "type": "array",
            "minItems": 1,
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "ad_id": {"type": "string", "pattern": "^[0-9]+$"},
                    "headlines": {
                        "type": "array",
                        "minItems": 3,
                        "maxItems": 15,
                        "items": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 30,
                        },
                    },
                    "descriptions": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 4,
                        "items": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 90,
                        },
                    },
                    "final_urls": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "path1": {"type": "string", "maxLength": 15},
                    "path2": {"type": "string", "maxLength": 15},
                },
                "required": ["ad_id"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["customer_id", "updates"],
    "additionalProperties": False,
}


def _build_params_summary(updates: list[dict[str, Any]]) -> dict[str, Any]:
    """Audit-safe: counts only, NO copy text."""
    fields_updated: Counter[str] = Counter()
    for u in updates:
        for f in ("headlines", "descriptions", "final_urls", "path1", "path2"):
            if f in u:
                fields_updated[f] += 1
    return {
        "count": len(updates),
        "fields_updated_distribution": dict(fields_updated),
        "unique_ads": len({u["ad_id"] for u in updates}),
    }


@register_tool(
    name="update_rsa",
    description=(
        "[DEFER] Modifica 1-5 RSAs existentes. Cada update tem ad_id + pelo menos 1 dos "
        "campos mutaveis: headlines (3-15 × 30 chars), descriptions (2-4 × 90 "
        "chars), final_urls (1+), path1/path2 (15 chars cada). Listas fornecidas "
        "SUBSTITUEM as existentes (semantics proto-plus + field_mask). Sempre "
        "CONFIRM. Pre-flight rejeita ad inexistente, type != RESPONSIVE_SEARCH_AD, "
        "ad_group REMOVED, ou campaign non-SEARCH. Para mudar status, use "
        "update_ad_status. Atualizacoes afetam serving immediately mas Google "
        "pode re-aprovar (geralmente minutos)."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def update_rsa(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    updates = args["updates"]
    target_count = len(updates)

    shape_error = _validate_updates_have_mutable_field(updates)
    if shape_error:
        return error_envelope("update_rsa", shape_error)

    error = await validate_existing_rsas_for_update(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        updates=updates,
    )
    if error:
        return error_envelope("update_rsa", error)

    risk = classify(operation="update_rsa", params={"target_count": target_count})

    params_summary = _build_params_summary(updates)
    fields_dist = params_summary["fields_updated_distribution"]
    unique_ads = params_summary["unique_ads"]
    summary = (
        f"Atualizar {target_count} RSA(s) ({unique_ads} unicos). Campos: "
        f"{', '.join(f'{f}({n})' for f, n in sorted(fields_dist.items()))}."
    )

    payload = {
        "updates": updates,
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
            operation_type="update_rsa",
            payload=payload,
            blast_summary=summary,
        )

    preview = [
        {
            "ad_id": u["ad_id"],
            "fields_updated": sorted(k for k in u if k != "ad_id"),
        }
        for u in updates
    ]

    return preview_envelope(
        "update_rsa",
        customer_id,
        summary,
        token,
        confirmation_reason=risk.reason,
        updates_preview=preview,
    )
