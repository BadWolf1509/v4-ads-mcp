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
from src.governance.rate_limit import (
    before_call,
    hash_developer_token,
    record_actual,
)

log = structlog.get_logger(__name__)

_REQUEST_ID_METADATA_KEY = "request-id"

# Eagerly import builders so they're registered before any tool runs.
import_all_builders()


def _extract_request_id(response: Any) -> str | None:
    """Extract the Google Ads request ID from the gRPC trailing metadata.

    In the google-ads Python SDK the response object returned by service
    calls (e.g. ``ga_service.mutate()``) is a
    ``_UnaryUnaryWrapper`` — a ``grpc.Call`` subclass injected by the
    ``ExceptionInterceptor``.  The ``request-id`` header lives in the
    **trailing** metadata of the underlying gRPC call.

    The SDK's ``_UnaryUnaryWrapper.trailing_metadata()`` has a known
    copy-paste bug: it delegates to ``initial_metadata()`` instead of
    ``trailing_metadata()``, so calling it directly always returns the
    wrong headers.  We therefore reach into the private ``_underlay_call``
    attribute to bypass the buggy wrapper.

    Falls back gracefully to ``None`` when:
    - the SDK is not installed (unit tests with plain ``MagicMock``),
    - the private attribute is absent (future SDK refactor),
    - trailing metadata is empty or the key is missing.
    """
    try:
        underlay = response._underlay_call
        for key, value in underlay.trailing_metadata() or []:
            if key == _REQUEST_ID_METADATA_KEY:
                return value or None
    except AttributeError:
        pass
    return None


async def run_mutation(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    operation_type: str,
    payload: dict[str, Any],
    target_count: int,
) -> dict[str, Any]:
    """Execute a mutation. Returns {google_request_id, applied_count, partial_failures}."""
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
            ga_service = client.get_service("GoogleAdsService")
            request = client.get_type("MutateGoogleAdsRequest")
            request.customer_id = customer_id
            for op in operations:
                request.mutate_operations.append(op)
            response = ga_service.mutate(request=request)
            # Capture request_id from gRPC trailing metadata (key "request-id").
            google_request_id = _extract_request_id(response)
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

        return {
            "google_request_id": google_request_id,
            "applied_count": target_count,
            "partial_failures": [],
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
                params_summary={"keys": sorted(payload.keys())},  # don't log full payload
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
            if operation_type == "apply_recommendation":
                response = execute_apply_recommendation(client, customer_id, payload)
            elif operation_type == "dismiss_recommendation":
                response = execute_dismiss_recommendation(client, customer_id, payload)
            else:
                raise ValueError(f"Unknown recommendation operation: {operation_type}")
            google_request_id = _extract_request_id(response)
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
