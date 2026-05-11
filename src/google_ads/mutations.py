"""Shared executor for write tools.

run_mutation handles:
  - rate limit reservation
  - building the mutate operations via registered builders
  - executing via GoogleAdsService.mutate
  - audit logging (always for mutations — sensitive)
  - error translation
"""

import time
from typing import Any
from uuid import UUID

import structlog

from src.config import get_settings
from src.db import connection
from src.db.repositories import audit_log
from src.google_ads.client import build_client_for_manager
from src.google_ads.errors import to_friendly
from src.google_ads.mutates._common import get_builder, import_all_builders
from src.google_ads.request_id import (
    get_capture_interceptor,
    get_request_id,
    reset_request_id,
)
from src.governance.rate_limit import (
    before_call,
    hash_developer_token,
    record_actual,
)

log = structlog.get_logger(__name__)

# Eagerly import builders so they're registered before any tool runs.
import_all_builders()


async def run_mutation(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    operation_type: str,
    payload: dict[str, Any],
    target_count: int,
    partial_failure: bool = False,
    params_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a mutation. Returns {google_request_id, applied_count, partial_failures}.

    Args:
        partial_failure: When True, sets request.partial_failure_mode = PARTIAL_FAILURE.
            Individual op failures don't abort the request; per-op status is returned
            in `partial_failures` list (each entry: {index, status: 'added'|'failed', error}).
            Callers are responsible for re-mapping specific error codes (e.g. CRITERION_EXISTS
            or DUPLICATE_KEYWORD → status='already_exists') in their tool-layer response.
            When False (default), any error aborts.
        params_summary: Optional override for audit_log.params_summary. When None,
            defaults to {"keys": sorted(payload.keys())}.
    """
    settings = get_settings()
    token_id = hash_developer_token(settings.google_ads_developer_token)
    started = time.monotonic()
    pool = connection.get_pool()
    google_request_id: str | None = None
    error_message: str | None = None
    status = "success"

    try:
        async with pool.acquire() as conn:
            await before_call(conn, token_id, estimated_ops=max(1, target_count))

        builder = get_builder(operation_type)
        if builder is None:
            raise ValueError(f"No mutate builder registered for '{operation_type}'")

        client = await build_client_for_manager(manager_id=manager_id)

        try:
            operations = builder(client, customer_id, payload)
            # Inject the request-id-capturing interceptor — see request_id.py.
            ga_service = client.get_service(
                "GoogleAdsService", interceptors=[get_capture_interceptor()]
            )
            request = client.get_type("MutateGoogleAdsRequest")
            request.customer_id = customer_id
            for op in operations:
                request.mutate_operations.append(op)
            if partial_failure:
                request.partial_failure_mode = client.enums.PartialFailureModeEnum.PARTIAL_FAILURE
            reset_request_id()
            response = ga_service.mutate(request=request)
            google_request_id = get_request_id()

            # Parse per-op status when partial_failure is enabled
            per_op_results: list[dict[str, Any]] = []
            if partial_failure:
                if hasattr(response, "mutate_operation_responses"):
                    for idx, op_resp in enumerate(response.mutate_operation_responses):
                        if op_resp.HasField("partial_failure_error"):
                            per_op_results.append(
                                {
                                    "index": idx,
                                    "status": "failed",
                                    "error": op_resp.partial_failure_error.message,
                                }
                            )
                        else:
                            per_op_results.append(
                                {
                                    "index": idx,
                                    "status": "added",
                                    "error": None,
                                }
                            )
                else:
                    log.warning(
                        "partial_failure_response_missing_operation_responses",
                        operation=operation_type,
                        customer_id=customer_id,
                        target_count=target_count,
                    )
        except Exception as e:
            # Log the raw exception with traceback BEFORE wrapping it in the
            # friendly PT-BR error. Without this, when to_friendly falls
            # through to the generic "Erro inesperado..." (because the SDK
            # exception had no `.failure` attribute), there's no signal in
            # production logs about what actually went wrong.
            log.exception(
                "mutation_raw_exception",
                operation=operation_type,
                customer_id=customer_id,
                target_count=target_count,
                exc_type=type(e).__name__,
                exc_module=type(e).__module__,
            )
            raise to_friendly(e) from e

        applied_count = target_count
        if partial_failure and per_op_results:
            applied_count = sum(1 for r in per_op_results if r["status"] == "added")
        return {
            "google_request_id": google_request_id,
            "applied_count": applied_count,
            "partial_failures": per_op_results,
        }
    except Exception as e:
        status = "error"
        error_message = str(e)
        raise
    finally:
        duration_ms = int((time.monotonic() - started) * 1000)
        async with pool.acquire() as conn:
            await record_actual(
                conn,
                token_id,
                actual_ops=target_count,
                estimated_ops=max(1, target_count),
            )
            # Always audit mutations (sensitive — every change is logged)
            await audit_log.record(
                conn,
                manager_id=manager_id,
                session_id=session_id,
                customer_id=customer_id,
                action_type="mutate",
                operation=operation_type,
                target_count=target_count,
                params_summary=params_summary
                if params_summary is not None
                else {"keys": sorted(payload.keys())},
                google_request_id=google_request_id,
                status=status,
                error_message=error_message,
                duration_ms=duration_ms,
            )
        log.info(
            "mutation_executed",
            operation=operation_type,
            customer_id=customer_id,
            target_count=target_count,
            status=status,
        )


async def run_recommendation_action(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    operation_type: str,  # 'apply_recommendation' | 'dismiss_recommendation'
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Execute a recommendation action via RecommendationService.

    Different from run_mutation because recommendations use a dedicated
    service, not the generic GoogleAdsService.mutate path. Same audit +
    rate limit hooks.
    """
    from src.google_ads.mutates.recommendations import (
        execute_apply_recommendation,
        execute_dismiss_recommendation,
    )

    settings = get_settings()
    token_id = hash_developer_token(settings.google_ads_developer_token)
    started = time.monotonic()
    pool = connection.get_pool()
    google_request_id: str | None = None
    error_message: str | None = None
    status = "success"
    target_count = 1  # one recommendation per call

    try:
        async with pool.acquire() as conn:
            await before_call(conn, token_id, estimated_ops=1)

        client = await build_client_for_manager(manager_id=manager_id)

        try:
            reset_request_id()
            if operation_type == "apply_recommendation":
                execute_apply_recommendation(client, customer_id, payload)
            elif operation_type == "dismiss_recommendation":
                execute_dismiss_recommendation(client, customer_id, payload)
            else:
                raise ValueError(f"Unknown recommendation operation: {operation_type}")
            google_request_id = get_request_id()
        except Exception as e:
            raise to_friendly(e) from e

        return {
            "google_request_id": google_request_id,
            "applied_count": 1,
        }
    except Exception as e:
        status = "error"
        error_message = str(e)
        raise
    finally:
        duration_ms = int((time.monotonic() - started) * 1000)
        async with pool.acquire() as conn:
            await record_actual(
                conn,
                token_id,
                actual_ops=1,
                estimated_ops=1,
            )
            await audit_log.record(
                conn,
                manager_id=manager_id,
                session_id=session_id,
                customer_id=customer_id,
                action_type="mutate",
                operation=operation_type,
                target_count=target_count,
                params_summary={"keys": sorted(payload.keys())},
                google_request_id=google_request_id,
                status=status,
                error_message=error_message,
                duration_ms=duration_ms,
            )
        log.info(
            "recommendation_action_executed",
            operation=operation_type,
            customer_id=customer_id,
            status=status,
        )
