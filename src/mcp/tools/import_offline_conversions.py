# bucket: defer
"""Tool: import_offline_conversions — upload N offline conversions via ConversionUploadService.

Sprint 3b.26. First V4 tool that does NOT use GoogleAdsService.mutate. Uses
ConversionUploadService.UploadClickConversions instead — different request/response
shape. F13 cross-cutting NOT applied (custom response with applied_count + failures).

Always-CONFIRM (creates ROAS-attribution signals — sensitive per spec §7.1).
partial_failure=True per Google docs: individual conversion failures don't block batch.

V4 invariants hardcoded (no schema fields):
- currency_code = "BRL"
- conversion_date_time e interpretado no FUSO DA CONTA (google_ads_accounts.time_zone) e o
  builder anexa o offset desse fuso (F146: era "-03:00" fixo; 2 contas sao UTC-4)
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
from datetime import datetime, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from src.db import connection
from src.google_ads.account_clock import resolve_account_zone
from src.google_ads.queries._common import validate_conversion_action_for_upload
from src.governance.blast_radius import classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._mutate_common import error_envelope, preview_envelope
from src.mcp.tools._registry import register_tool

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
                            "Timestamp no relogio LOCAL da conta (fuso do inventario; o builder anexa o offset — F146). "
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
    return error_envelope("import_offline_conversions", f"conversions[{idx}]: {msg}")


def _validate_payload_shape(payload: dict[str, Any], *, tz: tzinfo) -> dict[str, Any] | None:
    """Cross-field validation Layer 2 (Sprint 3b.19B.1 convention).

    5 checks (per-conversion loop + batch-level).
    Returns None if valid, error dict if invalid.

    F146: `tz` e o fuso da CONTA, obrigatorio e sem default. O gestor digita o
    relogio da parede; interpreta-lo em -03:00 fixo rejeitava como "futura" uma
    conversao das 23:30 numa conta UTC-4.
    """
    conversions = payload["conversions"]
    now_brt = datetime.now(tz)

    for idx, conv in enumerate(conversions):
        # Check 1: conversion_date_time parseability (defense-in-depth vs Layer 1 regex)
        try:
            dt = datetime.strptime(conv["conversion_date_time"], "%Y-%m-%d %H:%M:%S")
            dt = dt.replace(tzinfo=tz)
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
        elapsed = now_brt - dt
        if elapsed > timedelta(days=90):
            days_ago = elapsed.days
            return _err(
                idx,
                f"conversion_date_time '{conv['conversion_date_time']}' tem "
                f"{days_ago} dias; Google só aceita até 90 dias",
            )

    # Check 4: gclid duplicates dentro do batch
    gclids = [c["gclid"] for c in conversions]
    if len(gclids) != len(set(gclids)):
        dupes = [g for g, count in Counter(gclids).items() if count > 1]
        return error_envelope(
            "import_offline_conversions",
            (
                f"gclids duplicados no batch: {dupes[:3]}"
                f"{' ...' if len(dupes) > 3 else ''}. "
                "Use order_id pra dedupe se intencional."
            ),
        )

    # Check 5: order_id duplicates (se presente)
    order_ids = [c["order_id"] for c in conversions if "order_id" in c]
    if order_ids and len(order_ids) != len(set(order_ids)):
        dupes = [o for o, count in Counter(order_ids).items() if count > 1]
        return error_envelope(
            "import_offline_conversions",
            (
                f"order_id duplicados no batch: {dupes[:3]}"
                f"{' ...' if len(dupes) > 3 else ''}. "
                "Cada conversão deve ter order_id único."
            ),
        )

    return None


def _build_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Audit-safe summary: counts/sums only, NO gclid content per spec §3.6.

    Returns: conversion_count, sum_value_brl, date_range, gclids_distinct,
    order_ids_present, conversion_action_id.
    """
    conversions = payload["conversions"]
    dates = sorted(c["conversion_date_time"] for c in conversions)
    distinct_gclids = {c["gclid"] for c in conversions}
    order_ids_present = sum(1 for c in conversions if "order_id" in c)
    sum_value = sum(float(c["conversion_value_brl"]) for c in conversions)

    return {
        "conversion_count": len(conversions),
        "sum_value_brl": round(sum_value, 2),
        "date_range": {
            "earliest": dates[0] if dates else "",
            "latest": dates[-1] if dates else "",
        },
        "gclids_distinct": len(distinct_gclids),
        "order_ids_present": order_ids_present,
        "conversion_action_id": payload["conversion_action_id"],
    }


@register_tool(
    name="import_offline_conversions",
    description=(
        "[DEFER] Importa N conversões offline (1-100 por call) match-by-gclid pra "
        "Google Ads attribuir ROAS + alimentar Smart Bidding. Always-CONFIRM. "
        "Workflow V4 lead-gen: gestor captura gclid no URL da landing → salva "
        "no CRM → quando lead converte (WhatsApp confirmation, contrato assinado, "
        "pagamento) → chama tool com batch de gclids + datas + valores. V4 "
        "invariants hardcoded: currency_code=BRL; timezone = o da CONTA no inventario (F146: era -03:00 fixo), "
        "consent.ad_user_data=GRANTED (LGPD V4-aligned). Pre-flight valida "
        "conversion_action_id existe + tem type=UPLOAD_CLICKS. partial_failure=True: "
        "conversões individuais com erro (gclid expirado, data inválida) são "
        "reportadas em response.failures[] mas não bloqueiam o batch. Sprint 3b.26 "
        "introduz dispatcher run_conversion_upload paralelo a run_mutation."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def import_offline_conversions(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    conversion_action_id = args["conversion_action_id"]

    # Layer 2: Runtime payload validation (Sprint 3b.19B.1 convention).
    # IMPORTANT: _validate_payload_shape returns the FULL error dict
    # (NOT just a string like Sprint 3b.24 create_campaign).
    # F146: o fuso vem do inventario e e resolvido UMA vez. Sem fuso, recusa —
    # e um MUTATE que grava timestamp no Google; offset chutado e corrupcao de
    # dado em conta de cliente, nao ruido (decisao registrada 03/09).
    tz_name = await resolve_account_zone(customer_id)
    if tz_name is None:
        return error_envelope(
            "import_offline_conversions",
            (
                f"A conta {customer_id} nao tem fuso horario no inventario "
                "(google_ads_accounts.time_zone). Sem ele o timestamp das conversoes "
                "iria ao Google com offset chutado. Rode o resync de contas e tente de novo."
            ),
            customer_id=customer_id,
        )
    zone = ZoneInfo(tz_name)

    shape_error = _validate_payload_shape(args, tz=zone)
    if shape_error is not None:
        return shape_error

    # Layer 3: Async pre-flight (GAQL conversion_action lookup)
    pre_flight_error = await validate_conversion_action_for_upload(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        conversion_action_id=conversion_action_id,
    )
    if pre_flight_error is not None:
        return error_envelope(
            "import_offline_conversions", pre_flight_error, customer_id=customer_id
        )

    summary = _build_summary(args)
    # O preview MOSTRA o fuso e o offset que vao ser enviados — o gestor confirma sabendo.
    summary["time_zone"] = tz_name
    summary["utc_offset"] = (
        datetime.now(zone).strftime("%z")[:3] + ":" + datetime.now(zone).strftime("%z")[3:]
    )
    target_count = summary["conversion_count"]

    risk = classify(
        operation="import_offline_conversions",
        params={"target_count": target_count},
    )

    blast_summary = (
        f"Importar {summary['conversion_count']} conversões offline "
        f"(sum R$ {summary['sum_value_brl']:.2f}, range "
        f"{summary['date_range']['earliest']} → {summary['date_range']['latest']}) "
        f"pra conversion_action_id={conversion_action_id}"
    )

    payload = {
        **args,
        "__target_count__": target_count,
        "__params_summary__": summary,
        "__time_zone__": tz_name,  # F146: preview e upload usam o MESMO fuso
    }

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="import_offline_conversions",
            payload=payload,
            blast_summary=blast_summary,
        )

    return preview_envelope(
        "import_offline_conversions",
        customer_id,
        blast_summary,
        token,
        confirmation_reason=risk.reason,
        summary=summary,
    )
