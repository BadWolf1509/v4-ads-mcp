"""Customer Match user list upload — hashing utilities + builder + dispatcher.

Sprint 3b.28 — segundo dispatcher non-mutate fora de GoogleAdsService.mutate
(paralelo a src/google_ads/conversions.py do Sprint 3b.26).

SHA-256 hex digest client-side per Google Ads Customer Match spec.
V4 invariants: phone default country_code +55 (BR-only V4), LGPD consent
GRANTED hardcoded em metadata, enable_partial_failure=True.
"""

from __future__ import annotations

import hashlib
import re
import time
from typing import Any
from uuid import UUID

import structlog

from src.blocking import run_blocking
from src.config import get_settings
from src.db import connection
from src.db.repositories import audit_log
from src.google_ads.access import ensure_account_access
from src.google_ads.client import build_client_for_manager
from src.google_ads.errors import to_friendly
from src.google_ads.request_id import get_request_id, reset_request_id
from src.governance.bookkeeping import best_effort
from src.governance.rate_limit import (
    before_call,
    hash_developer_token,
    record_actual,
)

log = structlog.get_logger(__name__)


def _normalize_and_hash_email(plaintext: str) -> str:
    """SHA-256 hex digest após lowercase + remove ALL whitespace.

    Per Google Customer Match spec:
    https://developers.google.com/google-ads/api/docs/remarketing/audience-types/customer-match#data-formatting
    """
    normalized = "".join(plaintext.split()).lower()
    return hashlib.sha256(normalized.encode()).hexdigest()


def _normalize_and_hash_phone(plaintext: str) -> str:
    """E.164 normalize + SHA-256 hex digest.

    V4 invariant: phone sem country code prefix (+) → assume +55 (BR).
    Strip non-digit chars except leading +. Numero BR começando com 0 (DDD
    legacy) tem 0 removido antes de adicionar +55.
    """
    digits = re.sub(r"[^\d+]", "", plaintext)
    if not digits.startswith("+"):
        digits = "+55" + digits.lstrip("0")
    return hashlib.sha256(digits.encode()).hexdigest()


def _build_user_data_operations(
    client: Any,
    operation_type: str,
    hashed_members: list[dict[str, Any]],
) -> list[Any]:
    """Build OfflineUserDataJobOperation list from hashed members.

    Each member → 1 UserData with 1-2 user_identifiers (hashed_email and/or
    hashed_phone_number) → 1 OfflineUserDataJobOperation.

    operation_type: "add" (operation.create = user_data) or
                    "remove" (operation.remove = user_data).
    """
    operations: list[Any] = []
    for member in hashed_members:
        user_data = client.get_type("UserData")

        if "hashed_email" in member:
            identifier = client.get_type("UserIdentifier")
            identifier.hashed_email = member["hashed_email"]
            user_data.user_identifiers.append(identifier)

        if "hashed_phone_number" in member:
            identifier = client.get_type("UserIdentifier")
            identifier.hashed_phone_number = member["hashed_phone_number"]
            user_data.user_identifiers.append(identifier)

        op = client.get_type("OfflineUserDataJobOperation")
        if operation_type == "add":
            op.create = user_data
        else:  # "remove"
            op.remove = user_data
        operations.append(op)

    return operations


async def run_offline_user_data_job(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    user_list_id: str,
    operation_type: str,
    hashed_members: list[dict[str, Any]],
) -> dict[str, Any]:
    """3-step Google API sequence pra Customer Match upload:

    1. create_offline_user_data_job → job_resource
    2. add_offline_user_data_job_operations (operations[], enable_partial_failure=True)
    3. run_offline_user_data_job (fire-and-forget; backend processa em horas)

    Returns dict com job_resource_name + 3 provider_request_ids + members_submitted.

    Sprint 3b.28 — segundo dispatcher non-mutate, paralelo a run_conversion_upload
    do Sprint 3b.26.
    """
    settings = get_settings()
    # F91 — gate roda a cada request MCP e e read pre-operacao (o audit de
    # negacao so acontece no caminho de erro, que ja levanta e nao e retentado).
    await connection.run_with_reconnect(
        lambda conn: ensure_account_access(
            conn,
            manager_id=manager_id,
            customer_id=customer_id,
            session_id=session_id,
            operation_name="upload_customer_match_list",
            level="write",
        )
    )
    log.info(
        "run_offline_user_data_job_start",
        customer_id=customer_id,
        user_list_id=user_list_id,
        operation_type=operation_type,
        member_count=len(hashed_members),
    )

    token_id = hash_developer_token(settings.google_ads_developer_token)
    started = time.monotonic()
    pool = connection.get_pool()
    member_count = len(hashed_members)
    # 3 chamadas de API (create/add/run) OU o volume de membros, o que for maior —
    # reserva de quota conservadora contra o cap diário do developer token.
    estimated_ops = max(3, member_count)
    # params_summary SEM PII: hashed_members deriva de e-mail/telefone → nunca logar.
    audit_params = {
        "user_list_id": user_list_id,
        "operation": operation_type,
        "member_count": member_count,
    }
    # provider_request_id acumula o último request-id bem-sucedido (útil no audit de erro
    # pra saber em qual das 3 etapas parou).
    provider_request_id = ""
    status = "success"
    error_message: str | None = None
    friendly_error: Exception | None = None
    original_error: Exception | None = None
    reserved = False

    try:
        # Reserve quota: global (developer token) + per-manager cap. Transacao
        # EXTERNA torna as duas reservas tudo-ou-nada (before_call's internal
        # conn.transaction() vira SAVEPOINT; raise em qualquer uma desfaz ambas).
        async with pool.acquire() as conn, conn.transaction():
            await before_call(conn, token_id, estimated_ops=estimated_ops)
            await before_call(
                conn,
                f"mgr:{manager_id}",
                estimated_ops=estimated_ops,
                daily_limit=settings.manager_daily_quota,
            )
        reserved = True

        client = await build_client_for_manager(manager_id=manager_id)
        service = client.get_service("OfflineUserDataJobService")

        # Step 1: Create job
        reset_request_id()
        job = client.get_type("OfflineUserDataJob")
        job.type_ = client.enums.OfflineUserDataJobTypeEnum.CUSTOMER_MATCH_USER_LIST
        job.customer_match_user_list_metadata.user_list = (
            f"customers/{customer_id}/userLists/{user_list_id}"
        )
        job.customer_match_user_list_metadata.consent.ad_user_data = (
            client.enums.ConsentStatusEnum.GRANTED
        )
        job.customer_match_user_list_metadata.consent.ad_personalization = (
            client.enums.ConsentStatusEnum.GRANTED
        )

        # F86: as 3 chamadas gRPC (todas bloqueantes) saem do event loop juntas —
        # sao sequencialmente dependentes, entao um salto de thread so evita 3
        # round-trips de scheduling. Cada request-id e lido DENTRO da thread: o
        # interceptor o grava num ContextVar, e `to_thread` copia o contexto sem
        # propagar de volta (ver mutations.py).
        def _rodar_job() -> tuple[str, str, str, str]:
            create_response = service.create_offline_user_data_job(customer_id=customer_id, job=job)
            job_resource_local = create_response.resource_name
            create_id = get_request_id() or "unknown"

            # Step 2: Add operations
            reset_request_id()
            operations = _build_user_data_operations(client, operation_type, hashed_members)
            add_request = client.get_type("AddOfflineUserDataJobOperationsRequest")
            add_request.resource_name = job_resource_local
            add_request.operations = operations
            add_request.enable_partial_failure = True
            service.add_offline_user_data_job_operations(request=add_request)
            add_id = get_request_id() or "unknown"

            # Step 3: Run job (fire-and-forget)
            reset_request_id()
            service.run_offline_user_data_job(resource_name=job_resource_local)
            run_id = get_request_id() or "unknown"

            return job_resource_local, create_id, add_id, run_id

        job_resource, create_req_id, add_req_id, run_req_id = await run_blocking(_rodar_job)
        # O audit guarda o ultimo (o do run); a resposta expoe os tres.
        provider_request_id = run_req_id

    except Exception as e:
        status = "error"
        error_message = str(e)
        log.exception(
            "run_offline_user_data_job_failed",
            customer_id=customer_id,
            user_list_id=user_list_id,
            operation_type=operation_type,
        )
        friendly_error = to_friendly(e)
        original_error = e
    finally:
        duration_ms = int((time.monotonic() - started) * 1000)
        # Reconcile counters SO se a reserva foi persistida (reserved=True) —
        # sem reserva nao ha nada pra reconciliar (F73 — reconciliar mesmo assim
        # decrementaria o contador sem contrapartida).
        actual_ops = estimated_ops if status == "success" else 0
        # F83: best-effort e independentes — os membros ja foram enviados ao
        # Google quando este bloco roda.
        if reserved:
            async with (
                best_effort(
                    "customer_match_quota_reconcile_failed",
                    operation="upload_customer_match_list",
                    customer_id=customer_id,
                ),
                pool.acquire() as conn,
                conn.transaction(),
            ):
                await record_actual(
                    conn, token_id, actual_ops=actual_ops, estimated_ops=estimated_ops
                )
                await record_actual(
                    conn,
                    f"mgr:{manager_id}",
                    actual_ops=actual_ops,
                    estimated_ops=estimated_ops,
                )
        # Audit SEMPRE roda (mutate PII exige rastro; LGPD) — inclusive quando
        # reserved=False (negacao por quota deve aparecer no audit). Se a escrita
        # falhar, o best_effort garante rastro ERROR alertavel (F83) em vez de
        # sumir junto com o resultado.
        async with (
            best_effort(
                "customer_match_audit_write_failed",
                operation="upload_customer_match_list",
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
                operation="upload_customer_match_list",
                target_count=member_count,
                params_summary=audit_params,
                provider_request_id=provider_request_id,
                status=status,
                error_message=error_message,
                duration_ms=duration_ms,
            )

    if friendly_error is not None:
        # Raise (não retorna dict de erro): apply_change espera dict de sucesso;
        # o friendly propaga pro _error_envelope como mensagem PT-BR pro cliente.
        raise friendly_error from original_error

    log.info(
        "run_offline_user_data_job_done",
        customer_id=customer_id,
        job_resource_name=job_resource,
        members_submitted=member_count,
    )

    return {
        "job_resource_name": job_resource,
        "provider_request_id_create_job": create_req_id,
        "provider_request_id_add_ops": add_req_id,
        "provider_request_id_run_job": run_req_id,
        "members_submitted": member_count,
    }
