"""Tool: import_offline_conversions — upload N offline conversions via ConversionUploadService.

Sprint 3b.26. First V4 tool that does NOT use GoogleAdsService.mutate. Uses
ConversionUploadService.UploadClickConversions instead — different request/response
shape. F13 cross-cutting NOT applied (custom response with applied_count + failures).

Always-CONFIRM (creates ROAS-attribution signals — sensitive per spec §7.1).
partial_failure=True per Google docs: individual conversion failures don't block batch.

V4 invariants hardcoded (no schema fields):
- currency_code = "BRL"
- conversion_date_time gets "-03:00" appended (BRT timezone, V4 BR-invariant)
- consent.ad_user_data = GRANTED (LGPD V4-aligned — gestor confirma consent antes CRM)
- partial_failure = True (Google's recommendation)
- debug_enabled = False

Proto field names verified via context7 on 2026-05-18:
- UploadClickConversionsRequest.partial_failure (Python — NOT partial_failure_enabled
  como Java SDK)
- ClickConversion.consent.ad_user_data = ConsentStatusEnum.GRANTED
- Failure detection: empty `result.conversion_action` em response.results[i] = failed row
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

_BRT = timezone(timedelta(hours=-3))

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["customer_id", "conversion_action_id", "conversions"],
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "conversion_action_id": {
            "type": "string",
            "pattern": "^[0-9]+$",
            "description": (
                "ID numérico (NOT resource path) da ConversionAction com type=UPLOAD_CLICKS. "
                "Pre-flight valida via GAQL."
            ),
        },
        "conversions": {
            "type": "array",
            "minItems": 1,
            "maxItems": 100,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["gclid", "conversion_date_time", "conversion_value_brl"],
                "properties": {
                    "gclid": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 256,
                        "description": (
                            "Google Click ID capturado no URL da landing. "
                            "String opaque — trust Google validation."
                        ),
                    },
                    "conversion_date_time": {
                        "type": "string",
                        "pattern": r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$",
                        "description": (
                            "Timestamp BRT (V4 invariant -03:00 anexado pelo builder). "
                            "Format: YYYY-MM-DD HH:MM:SS"
                        ),
                    },
                    "conversion_value_brl": {
                        "type": "number",
                        "minimum": 0.01,
                        "description": "Valor BRL da conversão (V4 invariant currency=BRL).",
                    },
                    "order_id": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 64,
                        "description": (
                            "Optional CRM lead ID pra dedupe Google-side. Google rejeita "
                            "conversion com mesmo (gclid, conversion_date_time, order_id) "
                            "já uploaded."
                        ),
                    },
                },
            },
        },
    },
}


def _err(idx: int, msg: str) -> dict[str, Any]:
    return {
        "status": "error",
        "error": f"conversions[{idx}]: {msg}",
        "operation": "import_offline_conversions",
    }


def _validate_payload_shape(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Cross-field validation Layer 2 (Sprint 3b.19B.1 convention).

    5 checks (per-conversion loop + batch-level).
    Returns None if valid, error dict if invalid.
    """
    conversions = payload["conversions"]
    now_brt = datetime.now(_BRT)

    for idx, conv in enumerate(conversions):
        # Check 1: conversion_date_time parseability (defense-in-depth vs Layer 1 regex)
        try:
            dt = datetime.strptime(conv["conversion_date_time"], "%Y-%m-%d %H:%M:%S")
            dt = dt.replace(tzinfo=_BRT)
        except ValueError:
            return _err(
                idx,
                f"conversion_date_time '{conv['conversion_date_time']}' "
                "não é YYYY-MM-DD HH:MM:SS válido",
            )

        # Check 2: conversion in past (5min clock skew tolerance)
        if dt > now_brt + timedelta(minutes=5):
            return _err(
                idx,
                f"conversion_date_time '{conv['conversion_date_time']}' está no futuro; "
                "Google rejeita conversões com timestamp futuro",
            )

        # Check 3: not too old (Google's 90-day click-to-conversion window)
        days_ago = (now_brt - dt).days
        if days_ago > 90:
            return _err(
                idx,
                f"conversion_date_time '{conv['conversion_date_time']}' tem "
                f"{days_ago} dias; Google só aceita até 90 dias",
            )

    # Check 4: gclid duplicates dentro do batch
    gclids = [c["gclid"] for c in conversions]
    if len(gclids) != len(set(gclids)):
        dupes = [g for g, count in Counter(gclids).items() if count > 1]
        return {
            "status": "error",
            "error": (
                f"gclids duplicados no batch: {dupes[:3]}"
                f"{'...' if len(dupes) > 3 else ''}. "
                "Use order_id pra dedupe se intencional."
            ),
            "operation": "import_offline_conversions",
        }

    # Check 5: order_id duplicates (se presente)
    order_ids = [c["order_id"] for c in conversions if "order_id" in c]
    if order_ids and len(order_ids) != len(set(order_ids)):
        dupes = [o for o, count in Counter(order_ids).items() if count > 1]
        return {
            "status": "error",
            "error": (
                f"order_id duplicados no batch: {dupes[:3]}. "
                "Cada conversão deve ter order_id único."
            ),
            "operation": "import_offline_conversions",
        }

    return None
