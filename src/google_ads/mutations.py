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
from src.google_ads._blocking import run_blocking
from src.google_ads.access import ensure_account_access
from src.google_ads.client import build_client_for_manager
from src.google_ads.errors import to_friendly
from src.google_ads.mutates._common import get_builder, import_all_builders
from src.google_ads.request_id import (
    get_capture_interceptor,
    get_request_id,
    reset_request_id,
)
from src.governance.bookkeeping import best_effort
from src.governance.rate_limit import (
    before_call,
    hash_developer_token,
    record_actual,
)

log = structlog.get_logger(__name__)

# Eagerly import builders so they're registered before any tool runs.
import_all_builders()


def _parse_partial_failures(
    response: Any,
    client: Any,
    *,
    operation_type: str,
    customer_id: str,
    target_count: int,
) -> list[dict[str, Any]]:
    """Classifica cada op de uma resposta partial_failure em added/failed (+ erro).

    Google Ads API surface (NOT what naive readings of the SDK suggest):
    - response.partial_failure_error is a google.rpc.Status at the TOP level (NOT a
      per-op field). Its `.code == 0` means no partial failures.
    - Per-op failure detection is via the response oneof: quando uma op falha, nenhum
      result field é setado no seu MutateOperationResponse, então
      `_pb.WhichOneof("response")` retorna None. Ops OK têm um field setado.
    - Per-op error MESSAGES vivem em partial_failure_error.details[] como um
      GoogleAdsFailure proto, cujo errors[].location.field_path_elements[0].index liga
      cada erro ao índice da op em mutate_operations.
    """
    per_op_results: list[dict[str, Any]] = []
    if not hasattr(response, "mutate_operation_responses"):
        log.warning(
            "partial_failure_response_missing_operation_responses",
            operation=operation_type,
            customer_id=customer_id,
            target_count=target_count,
        )
        return per_op_results

    # Build error-by-index map from the top-level partial_failure_error.
    error_by_index: dict[int, str] = {}
    pfe = getattr(response, "partial_failure_error", None)
    pfe_code = getattr(pfe, "code", 0) if pfe is not None else 0
    if pfe_code != 0:
        # The details list contains Any messages — at least one is a GoogleAdsFailure
        # with per-op locations. We unpack lazily.
        try:
            details = getattr(pfe, "details", []) or []
            for detail in details:
                # Convert proto-plus wrapper to raw pb if needed
                raw = detail._pb if hasattr(detail, "_pb") else detail
                # Duck-type check: must have type_url and Unpack (characteristic of
                # google.protobuf.any_pb2.Any). Avoids version-specific isinstance import.
                if not (hasattr(raw, "type_url") and hasattr(raw, "Unpack")):
                    continue
                # GoogleAdsFailure is the only detail Google sends here; check via
                # type_url substring rather than importing the version-specific proto
                # class (which differs across google-ads SDK versions).
                if "GoogleAdsFailure" not in raw.type_url:
                    continue
                failure_type = client.get_type("GoogleAdsFailure")
                failure_pb = failure_type._meta.pb()
                raw.Unpack(failure_pb)
                for gae in failure_pb.errors:
                    if gae.location.field_path_elements:
                        idx = gae.location.field_path_elements[0].index
                        error_by_index[int(idx)] = str(gae.message)
        except Exception:
            # If detail unpacking fails (SDK version drift, unexpected shape), fall back
            # to a generic error per failed op so the caller still sees something useful.
            log.exception(
                "partial_failure_detail_unpack_failed",
                operation=operation_type,
                customer_id=customer_id,
            )

    # Walk operation responses and classify by which oneof is set.
    for idx, op_resp in enumerate(response.mutate_operation_responses):
        # proto-plus wrapper exposes _pb; use raw WhichOneof
        raw = op_resp._pb if hasattr(op_resp, "_pb") else op_resp
        if hasattr(raw, "WhichOneof") and raw.WhichOneof("response") is not None:
            per_op_results.append({"index": idx, "status": "added", "error": None})
        else:
            per_op_results.append(
                {
                    "index": idx,
                    "status": "failed",
                    "error": error_by_index.get(idx, "Unknown partial failure"),
                }
            )
    return per_op_results


def _extract_resource_names(response: Any) -> list[str | None]:
    """resource_name de cada op bem-sucedida (None nas que falharam em partial_failure).

    Cada op OK tem WhichOneof("response") apontando pra um *_result message (ex.:
    ad_group_result) com o field resource_name (Sprint 3b.15 F13 fix). Retorna [] quando
    o field está ausente (rede de segurança contra SDK version drift).
    """
    resource_names: list[str | None] = []
    if hasattr(response, "mutate_operation_responses"):
        for op_resp in response.mutate_operation_responses:
            raw = op_resp._pb if hasattr(op_resp, "_pb") else op_resp
            oneof_field = raw.WhichOneof("response") if hasattr(raw, "WhichOneof") else None
            if oneof_field is None:
                resource_names.append(None)
            else:
                result_proto = getattr(raw, oneof_field)
                resource_names.append(getattr(result_proto, "resource_name", None) or None)
    return resource_names


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
    """Execute a mutation. Returns {provider_request_id, applied_count, partial_failures}.

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
    async with connection.get_pool().acquire() as conn:
        await ensure_account_access(
            conn,
            manager_id=manager_id,
            customer_id=customer_id,
            session_id=session_id,
            operation_name=operation_type,
            level="write",
        )
    token_id = hash_developer_token(settings.google_ads_developer_token)
    started = time.monotonic()
    pool = connection.get_pool()
    provider_request_id: str | None = None
    error_message: str | None = None
    status = "success"
    reserved = False

    try:
        # Reserve quota: global (developer token) + per-manager cap. Transacao
        # EXTERNA torna as duas reservas tudo-ou-nada (before_call's internal
        # conn.transaction() vira SAVEPOINT; raise em qualquer uma desfaz ambas).
        async with pool.acquire() as conn, conn.transaction():
            await before_call(conn, token_id, estimated_ops=max(1, target_count))
            await before_call(
                conn,
                f"mgr:{manager_id}",
                estimated_ops=max(1, target_count),
                daily_limit=settings.manager_daily_quota,
            )
        reserved = True

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
                # MutateGoogleAdsRequest.partial_failure is a plain bool field
                # (not an enum). When True, errors don't roll back successful
                # operations and per-op failures surface via
                # response.partial_failure_error.details (a GoogleAdsFailure).
                request.partial_failure = True
            reset_request_id()

            # F86: gRPC bloqueante sai do event loop. O request-id e lido AQUI
            # DENTRO de proposito: o interceptor o grava num ContextVar durante a
            # chamada, e `to_thread` COPIA o contexto — um get_request_id() do
            # lado do loop leria None e o provider_request_id sumiria do audit.
            def _mutar() -> tuple[Any, str | None]:
                resp = ga_service.mutate(request=request)
                return resp, get_request_id()

            response, provider_request_id = await run_blocking(_mutar)

            # Parse per-op status when partial_failure is enabled (helper isola o
            # parsing do proto — ver _parse_partial_failures).
            per_op_results: list[dict[str, Any]] = []
            if partial_failure:
                per_op_results = _parse_partial_failures(
                    response,
                    client,
                    operation_type=operation_type,
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

        # Extract resource_names from mutate_operation_responses (ver _extract_resource_names).
        resource_names = _extract_resource_names(response)

        return {
            "provider_request_id": provider_request_id,
            "applied_count": applied_count,
            "partial_failures": per_op_results,
            "resource_names": resource_names,
        }
    except Exception as e:
        status = "error"
        error_message = str(e)
        raise
    finally:
        duration_ms = int((time.monotonic() - started) * 1000)
        # F83: os dois blocos abaixo sao best-effort e INDEPENDENTES. Sem isso,
        # falha de conexao aqui descartaria o `return` de um mutate ja aplicado
        # no Google (e a falha da quota pularia o audit, por serem sequenciais).
        #
        # Reconcile counters SO se a reserva foi persistida (reserved=True) —
        # sem reserva nao ha nada pra reconciliar (F73 — reconciliar mesmo assim
        # decrementaria o contador sem contrapartida).
        if reserved:
            async with (
                best_effort(
                    "mutation_quota_reconcile_failed",
                    operation=operation_type,
                    customer_id=customer_id,
                ),
                pool.acquire() as conn,
                conn.transaction(),
            ):
                await record_actual(
                    conn,
                    token_id,
                    actual_ops=target_count,
                    estimated_ops=max(1, target_count),
                )
                await record_actual(
                    conn,
                    f"mgr:{manager_id}",
                    actual_ops=target_count,
                    estimated_ops=max(1, target_count),
                )
        async with (
            best_effort(
                "mutation_audit_write_failed",
                operation=operation_type,
                customer_id=customer_id,
                status=status,
            ),
            pool.acquire() as conn,
        ):
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
                provider_request_id=provider_request_id,
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
    provider_request_id: str | None = None
    error_message: str | None = None
    status = "success"
    target_count = 1  # one recommendation per call
    reserved = False

    try:
        async with pool.acquire() as conn:
            await ensure_account_access(
                conn,
                manager_id=manager_id,
                customer_id=customer_id,
                session_id=session_id,
                operation_name=operation_type,
                level="write",
            )

        # Reserve quota: global (developer token) + per-manager cap. Transacao
        # EXTERNA torna as duas reservas tudo-ou-nada (F73 — mesmo padrao dos
        # outros 4 executores; sem a 2a chave o cap por gestor teria um buraco
        # por onde apply/dismiss_recommendation passariam livres).
        async with pool.acquire() as conn, conn.transaction():
            await before_call(conn, token_id, estimated_ops=1)
            await before_call(
                conn,
                f"mgr:{manager_id}",
                estimated_ops=1,
                daily_limit=settings.manager_daily_quota,
            )
        reserved = True

        client = await build_client_for_manager(manager_id=manager_id)

        try:
            reset_request_id()
            if operation_type == "apply_recommendation":
                execute_apply_recommendation(client, customer_id, payload)
            elif operation_type == "dismiss_recommendation":
                execute_dismiss_recommendation(client, customer_id, payload)
            else:
                raise ValueError(f"Unknown recommendation operation: {operation_type}")
            provider_request_id = get_request_id()
        except Exception as e:
            raise to_friendly(e) from e

        return {
            "provider_request_id": provider_request_id,
            "applied_count": 1,
        }
    except Exception as e:
        status = "error"
        error_message = str(e)
        raise
    finally:
        duration_ms = int((time.monotonic() - started) * 1000)
        # F83: best-effort e independentes — falha aqui nao pode derrubar a acao
        # ja aplicada no Google, nem a quota pular o audit.
        #
        # Reconcile SO se reservou (F73). actual=estimated=1 da delta 0, mas o
        # gate mantem a simetria com os outros executores e nao decrementa se a
        # reserva falhou por QuotaExhausted.
        if reserved:
            async with (
                best_effort(
                    "recommendation_quota_reconcile_failed",
                    operation=operation_type,
                    customer_id=customer_id,
                ),
                pool.acquire() as conn,
                conn.transaction(),
            ):
                await record_actual(conn, token_id, actual_ops=1, estimated_ops=1)
                await record_actual(conn, f"mgr:{manager_id}", actual_ops=1, estimated_ops=1)
        async with (
            best_effort(
                "recommendation_audit_write_failed",
                operation=operation_type,
                customer_id=customer_id,
                status=status,
            ),
            pool.acquire() as conn,
        ):
            await audit_log.record(
                conn,
                manager_id=manager_id,
                session_id=session_id,
                customer_id=customer_id,
                action_type="mutate",
                operation=operation_type,
                target_count=target_count,
                params_summary={"keys": sorted(payload.keys())},
                provider_request_id=provider_request_id,
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
