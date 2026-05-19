"""Shared executor for conversion upload tools (Sprint 3b.26).

run_conversion_upload handles:
  - rate limit reservation (ops_used = len(conversions))
  - constructing UploadClickConversionsRequest direct (no @register_builder)
  - executing via ConversionUploadService.upload_click_conversions
  - audit logging (always — conversions are sensitive per spec §7.1)
  - parsing partial_failure response (empty result.conversion_action = failed row)
  - error translation

Parallels run_mutation but for ConversionUploadService (not GoogleAdsService.mutate).
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

import structlog

from src.config import get_settings
from src.db import connection
from src.db.repositories import audit_log
from src.google_ads.client import build_client_for_manager
from src.google_ads.errors import to_friendly
from src.google_ads.request_id import (
    get_request_id,
    reset_request_id,
)
from src.governance.rate_limit import (
    before_call,
    hash_developer_token,
    record_actual,
)

log = structlog.get_logger(__name__)


async def run_conversion_upload(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    operation_type: str,
    payload: dict[str, Any],
    target_count: int,
    params_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute an offline conversion upload via ConversionUploadService.

    Returns {status, operation, customer_id, applied_count, failed_count,
             failures: [...], google_request_id}.

    Sprint 3b.26 — first dispatcher that does NOT use GoogleAdsService.mutate.
    """
    settings = get_settings()
    token_id = hash_developer_token(settings.google_ads_developer_token)
    started = time.monotonic()
    pool = connection.get_pool()
    google_request_id: str | None = None
    applied_count = 0
    failed_count = 0
    failures: list[dict[str, Any]] = []
    status = "success"
    error_message: str | None = None

    try:
        async with pool.acquire() as conn:
            await before_call(conn, token_id, estimated_ops=max(1, target_count))

        client = await build_client_for_manager(manager_id=manager_id)

        # Build UploadClickConversionsRequest direct (no @register_builder).
        request = client.get_type("UploadClickConversionsRequest")
        request.customer_id = customer_id
        request.partial_failure = True  # Python field — NOT partial_failure_enabled
        # F42 (Sprint 3b.26.1): debug_enabled field REMOVED from v24
        # UploadClickConversionsRequest proto. Setting it raises AttributeError.
        # Smoke T7 caught: "Unknown field for UploadClickConversionsRequest: debug_enabled"

        conversion_action_path = (
            f"customers/{customer_id}/conversionActions/{payload['conversion_action_id']}"
        )
        consent_granted = client.enums.ConsentStatusEnum.GRANTED

        for conv in payload["conversions"]:
            click_conv = client.get_type("ClickConversion")
            click_conv.conversion_action = conversion_action_path
            click_conv.gclid = conv["gclid"]
            # V4 invariant: append -03:00 BRT timezone
            click_conv.conversion_date_time = f"{conv['conversion_date_time']}-03:00"
            click_conv.conversion_value = float(conv["conversion_value_brl"])
            click_conv.currency_code = "BRL"  # V4 invariant
            if "order_id" in conv:
                click_conv.order_id = conv["order_id"]
            # V4 invariant: LGPD consent GRANTED
            click_conv.consent.ad_user_data = consent_granted
            request.conversions.append(click_conv)

        reset_request_id()
        service = client.get_service("ConversionUploadService")
        response = service.upload_click_conversions(request=request)
        google_request_id = get_request_id()

        applied_count, failed_count, failures = _parse_upload_response(response, payload, client)

    except Exception as e:
        status = "error"
        error_message = str(e)
        # log.exception (not log.error) captures the raw traceback before
        # to_friendly() may swallow the original diagnostic. Mirrors
        # mutations.py pattern.
        log.exception(
            "conversion_upload_failed",
            operation=operation_type,
            customer_id=customer_id,
        )
        friendly = to_friendly(e)
        err_text = str(friendly)
        duration_ms = int((time.monotonic() - started) * 1000)
        async with pool.acquire() as conn:
            await record_actual(
                conn,
                token_id,
                actual_ops=0,
                estimated_ops=max(1, target_count),
            )
            await audit_log.record(
                conn,
                manager_id=manager_id,
                session_id=session_id,
                customer_id=customer_id,
                action_type="mutate",
                operation=operation_type,
                target_count=target_count,
                params_summary=params_summary or {"conversion_count": target_count},
                google_request_id=google_request_id or "",
                status=status,
                error_message=error_message,
                duration_ms=duration_ms,
            )
        return {
            "status": "error",
            "operation": operation_type,
            "customer_id": customer_id,
            "error": err_text,
            "google_request_id": google_request_id or "",
        }

    # Success path
    duration_ms = int((time.monotonic() - started) * 1000)
    async with pool.acquire() as conn:
        await record_actual(
            conn,
            token_id,
            actual_ops=len(payload["conversions"]),
            estimated_ops=max(1, target_count),
        )
        await audit_log.record(
            conn,
            manager_id=manager_id,
            session_id=session_id,
            customer_id=customer_id,
            action_type="mutate",
            operation=operation_type,
            target_count=target_count,
            params_summary=params_summary or {"conversion_count": target_count},
            google_request_id=google_request_id or "",
            status=status,
            error_message=error_message,
            duration_ms=duration_ms,
        )

    log.info(
        "conversion_upload_executed",
        operation=operation_type,
        customer_id=customer_id,
        target_count=target_count,
        applied_count=applied_count,
        failed_count=failed_count,
        status=status,
    )

    return {
        "status": "applied",
        "operation": operation_type,
        "customer_id": customer_id,
        "applied_count": applied_count,
        "failed_count": failed_count,
        "failures": failures,
        "google_request_id": google_request_id or "",
    }


def _parse_upload_response(
    response: Any, payload: dict[str, Any], client: Any
) -> tuple[int, int, list[dict[str, Any]]]:
    """Parse UploadClickConversionsResponse -> (applied, failed, failures list).

    Heuristic per Google docs: empty/falsy `result.conversion_action` in
    response.results[i] indicates row i failed. Detailed errors come from
    response.partial_failure_error.details[] (deserialized via GoogleAdsFailure).
    """
    input_conversions = payload["conversions"]
    applied = 0
    failures: list[dict[str, Any]] = []

    # Build row -> error_code/message mapping from partial_failure_error.details.
    row_errors: dict[int, dict[str, str]] = {}
    pfe = getattr(response, "partial_failure_error", None)
    pfe_code = getattr(pfe, "code", 0) if pfe is not None else 0
    if pfe_code != 0:
        try:
            details = getattr(pfe, "details", []) or []
            for detail in details:
                raw = detail._pb if hasattr(detail, "_pb") else detail
                if not (hasattr(raw, "type_url") and hasattr(raw, "Unpack")):
                    continue
                if "GoogleAdsFailure" not in raw.type_url:
                    continue
                failure_type = client.get_type("GoogleAdsFailure")
                failure_pb = failure_type._meta.pb()
                raw.Unpack(failure_pb)
                for gae in failure_pb.errors:
                    if gae.location.field_path_elements:
                        idx = int(gae.location.field_path_elements[0].index)
                        row_errors[idx] = {
                            "error_code": str(gae.error_code).split(":")[-1].strip() or "UNKNOWN",
                            "error_message": str(gae.message),
                        }
        except Exception:
            log.warning("partial_failure_detail_parse_failed", exc_info=True)

    # Walk results — empty conversion_action = failed row.
    for idx, result in enumerate(response.results):
        if not getattr(result, "conversion_action", None):
            err = row_errors.get(
                idx,
                {"error_code": "UNKNOWN", "error_message": "no detail"},
            )
            failures.append(
                {
                    "row_index": idx,
                    "gclid": input_conversions[idx]["gclid"],
                    **err,
                }
            )
        else:
            applied += 1

    return applied, len(failures), failures
