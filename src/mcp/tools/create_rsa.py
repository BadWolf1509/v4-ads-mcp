"""Tool: create_rsa - create 1-5 Responsive Search Ads in existing ad_groups.

Always-CONFIRM (creates sensitive per spec §7.1). Pre-flight validates parent
ad_groups: existence, not REMOVED, and parent campaign channel = SEARCH/SEARCH_PARTNERS.

Default status: PAUSED. RSAs require 3-15 headlines (30 chars each), 2-4
descriptions (90 chars each), 1+ final_urls. Optional path1/path2 (15 chars each).

NOT idempotent — Google permits multiple RSAs with same content in same ad_group.
"""

from collections import Counter
from typing import Any

from src.db import connection
from src.google_ads.queries._common import (
    validate_parent_ad_groups_for_rsa_create,
)
from src.governance.blast_radius import classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "rsas": {
            "type": "array",
            "minItems": 1,
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "ad_group_id": {"type": "string", "pattern": "^[0-9]+$"},
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
                    "status": {
                        "type": "string",
                        "enum": ["ENABLED", "PAUSED"],
                        "default": "PAUSED",
                    },
                },
                "required": ["ad_group_id", "headlines", "descriptions", "final_urls"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["customer_id", "rsas"],
    "additionalProperties": False,
}


def _build_params_summary(rsas: list[dict[str, Any]]) -> dict[str, Any]:
    """Audit-safe: counts only, NO copy text per spec §3.6."""
    status_counts = Counter(r.get("status", "PAUSED") for r in rsas)
    headlines_avg = sum(len(r["headlines"]) for r in rsas) / len(rsas)
    descriptions_avg = sum(len(r["descriptions"]) for r in rsas) / len(rsas)
    with_path1 = sum(1 for r in rsas if "path1" in r)
    with_path2 = sum(1 for r in rsas if "path2" in r)
    return {
        "count": len(rsas),
        "status_distribution": dict(status_counts),
        "avg_headlines": round(headlines_avg, 1),
        "avg_descriptions": round(descriptions_avg, 1),
        "with_path1": with_path1,
        "with_path2": with_path2,
        "unique_parent_ad_groups": len({r["ad_group_id"] for r in rsas}),
    }


@register_tool(
    name="create_rsa",
    description=(
        "Cria 1-5 Responsive Search Ads (RSAs) em ad_groups existentes. "
        "Cada RSA tem ad_group_id (parent) + headlines (3-15 strings, max 30 chars cada) "
        "+ descriptions (2-4 strings, max 90 chars cada) + final_urls (1+ URLs) + "
        "path1/path2 opcionais (display URL paths, max 15 chars cada) + status opcional "
        "(PAUSED default | ENABLED). Sempre CONFIRM (creates sensitive). Pre-flight "
        "rejeita ad_group inexistente, REMOVED, ou em campaign non-SEARCH. NOT "
        "idempotente — Google permite multiple RSAs com mesmo content. RSAs aparecem "
        "no Google Ads UI imediatamente apos apply mas serving so comeca apos approval "
        "(geralmente minutos)."
    ),
    input_schema=_SCHEMA,
)
async def create_rsa(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    rsas = args["rsas"]
    target_count = len(rsas)

    error = await validate_parent_ad_groups_for_rsa_create(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        rsas=rsas,
    )
    if error:
        return {"status": "error", "error": error, "operation": "create_rsa"}

    risk = classify(operation="create_rsa", params={"target_count": target_count})

    params_summary = _build_params_summary(rsas)
    status_dist = params_summary["status_distribution"]
    unique_ag = params_summary["unique_parent_ad_groups"]
    summary = (
        f"Criar {target_count} RSA(s) em {unique_ag} ad_group(s). "
        f"Status inicial: {', '.join(f'{s}({n})' for s, n in sorted(status_dist.items()))}. "
        f"Avg {params_summary['avg_headlines']} headlines + "
        f"{params_summary['avg_descriptions']} descriptions per RSA."
    )

    payload = {
        "rsas": rsas,
        "__target_count__": target_count,
        "__params_summary__": params_summary,
    }

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="create_rsa",
            payload=payload,
            blast_summary=summary,
        )

    preview = [
        {
            "ad_group_id": r["ad_group_id"],
            "headlines_count": len(r["headlines"]),
            "descriptions_count": len(r["descriptions"]),
            "final_urls_count": len(r["final_urls"]),
            "status": r.get("status", "PAUSED"),
            "has_path1": "path1" in r,
            "has_path2": "path2" in r,
        }
        for r in rsas
    ]

    return {
        "status": "dry_run",
        "operation": "create_rsa",
        "customer_id": customer_id,
        "blast_summary": summary,
        "rsas_preview": preview,
        "confirmation_token": token,
        "expires_in_minutes": 10,
        "to_apply": "Chame apply_change(confirmation_token=<token>) para aplicar.",
        "confirmation_reason": risk.reason,
    }
