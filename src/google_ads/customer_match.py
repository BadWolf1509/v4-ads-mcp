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
from dataclasses import dataclass, field
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
from src.google_ads.partial_failure import erros_por_indice
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


@dataclass
class _Progresso:
    """Onde a sequencia de 3 passos parou, visivel de FORA da thread (R1-I4).

    Os 3 RPCs rodam num closure entregue ao `run_blocking`. Quando um deles
    levanta, o closure morre sem devolver nada — e era por isso que o audit de
    erro gravava `provider_request_id=""`, contradizendo o comentario ao lado
    que prometia "o ultimo request-id bem-sucedido, util pra saber em qual das
    3 etapas parou". Este objeto e criado do lado de fora e preenchido a cada
    passo concluido, entao o `finally` le o progresso real.

    Nao ha atomicidade possivel aqui: sao 3 RPCs, e o Google nao oferece delete
    de `OfflineUserDataJob`. Falha no passo 3 deixa o job criado COM os membros
    anexados. O que da pra fazer — e o que se faz — e o padrao de saga sem
    compensacao: registrar o ponto de parada e o identificador do job, para que
    a trilha aponte para a PII que ficou la e a mensagem diga o estado real.
    """

    job_resource_name: str | None = None
    create_id: str = ""
    add_id: str = ""
    run_id: str = ""
    membros_recusados: list[dict[str, Any]] = field(default_factory=list)

    @property
    def etapa(self) -> str:
        """O passo que faltou concluir — `concluido` quando os 3 passaram."""
        if not self.create_id:
            return "create_job"
        if not self.add_id:
            return "add_operations"
        if not self.run_id:
            return "run_job"
        return "concluido"

    @property
    def pii_anexada(self) -> bool:
        """True quando o passo 2 concluiu: os membros JA estao no Google."""
        return bool(self.add_id)

    @property
    def ultimo_request_id(self) -> str:
        return self.run_id or self.add_id or self.create_id


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

    Returns dict com job_resource_name + 3 provider_request_ids + members_submitted
    (o que o Google ACEITOU) + members_failed + failures[].

    **Os 3 passos nao sao atomicos, e nao ha como torna-los** (R1-I4): sao 3
    RPCs e o Google nao oferece delete de `OfflineUserDataJob`. Falha depois do
    passo 2 deixa a lista de PII anexada la. O tratamento e o de uma saga sem
    compensacao: `_Progresso` registra onde parou, o audit guarda o
    `job_resource_name` e o `pii_anexada`, e o erro PT-BR diz ao gestor que os
    membros ja subiram — para ele nao repetir o upload e duplicar a lista.

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
    # R1-I4: o progresso nasce AQUI, fora do closure que roda na thread — era a
    # unica forma de o `finally` enxergar o ultimo request-id quando um dos 3
    # passos levanta. Antes, `provider_request_id` so era atribuido DEPOIS dos
    # tres, e o audit de erro gravava "" — exatamente o oposto do que o
    # comentario nesta linha prometia.
    progresso = _Progresso()
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
        def _rodar_job() -> None:
            # Cada passo grava seu request-id em `progresso` ANTES do proximo
            # comecar (R1-I4): se o passo seguinte levantar, o que ja concluiu
            # continua legivel de fora — inclusive `job_resource_name`, que e o
            # unico ponteiro para a PII que ficou no Google.
            create_response = service.create_offline_user_data_job(customer_id=customer_id, job=job)
            progresso.job_resource_name = create_response.resource_name
            progresso.create_id = get_request_id() or "unknown"

            # Step 2: Add operations
            reset_request_id()
            operations = _build_user_data_operations(client, operation_type, hashed_members)
            add_request = client.get_type("AddOfflineUserDataJobOperationsRequest")
            add_request.resource_name = progresso.job_resource_name
            add_request.operations = operations
            add_request.enable_partial_failure = True
            add_response = service.add_offline_user_data_job_operations(request=add_request)
            progresso.add_id = get_request_id() or "unknown"
            # R1-I3: `enable_partial_failure=True` pede ao Google que recuse
            # membro a membro em vez de derrubar o lote — e a resposta ia pro
            # lixo. Sem ler isto, `members_submitted` reportava o lote INTEIRO,
            # incluindo os hashes que o Google recusou (formato invalido,
            # identificador nao suportado). A resposta deste RPC nao tem lista
            # por-op: quem falhou so aparece pelo indice dentro do
            # `partial_failure_error`.
            progresso.membros_recusados = [
                {"index": idx, "error_code": e.error_code, "error_message": e.error_message}
                for idx, e in sorted(
                    erros_por_indice(
                        add_response,
                        client,
                        origem="run_offline_user_data_job",
                        customer_id=customer_id,
                    ).items()
                )
            ]

            # Step 3: Run job (fire-and-forget)
            reset_request_id()
            service.run_offline_user_data_job(resource_name=progresso.job_resource_name)
            progresso.run_id = get_request_id() or "unknown"

        await run_blocking(_rodar_job)

    except Exception as e:
        status = "error"
        error_message = str(e)
        log.exception(
            "run_offline_user_data_job_failed",
            customer_id=customer_id,
            user_list_id=user_list_id,
            operation_type=operation_type,
            etapa=progresso.etapa,
            job_resource_name=progresso.job_resource_name,
            pii_anexada=progresso.pii_anexada,
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
                # R1-I3/I4: o resumo passa a dizer o que ACONTECEU — onde a
                # sequencia parou, qual job ficou no Google, se a PII ja tinha
                # sido anexada quando parou, e quantos membros o Google
                # recusou. Segue sem PII: indice e codigo de erro, nunca hash.
                params_summary={
                    **audit_params,
                    "etapa": progresso.etapa,
                    "job_resource_name": progresso.job_resource_name,
                    "pii_anexada": progresso.pii_anexada,
                    "members_submitted": member_count - len(progresso.membros_recusados),
                    "members_failed": len(progresso.membros_recusados),
                },
                provider_request_id=progresso.ultimo_request_id,
                status=status,
                error_message=error_message,
                duration_ms=duration_ms,
            )

    if friendly_error is not None:
        # Raise (não retorna dict de erro): apply_change espera dict de sucesso;
        # o friendly propaga pro _error_envelope como mensagem PT-BR pro cliente.
        #
        # R1-I4: quando a PII ja subiu, a mensagem PT-BR precisa DIZER isso. Nao
        # ha rollback possivel (o Google nao apaga OfflineUserDataJob), e um
        # erro que omite o estado do outro lado convida o gestor a repetir a
        # chamada — anexando a mesma lista duas vezes.
        if progresso.pii_anexada:
            raise type(friendly_error)(
                f"{friendly_error} Atencao: os {member_count} membros JA foram enviados ao "
                f"Google (job {progresso.job_resource_name}); o que falhou foi o passo "
                f"'{progresso.etapa}'. NAO repita o upload — confira o status do job com "
                "run_gaql em offline_user_data_job antes de qualquer nova tentativa."
            ) from original_error
        raise friendly_error from original_error

    members_submitted = member_count - len(progresso.membros_recusados)
    log.info(
        "run_offline_user_data_job_done",
        customer_id=customer_id,
        job_resource_name=progresso.job_resource_name,
        members_submitted=members_submitted,
        members_failed=len(progresso.membros_recusados),
    )

    return {
        "job_resource_name": progresso.job_resource_name,
        "provider_request_id_create_job": progresso.create_id,
        "provider_request_id_add_ops": progresso.add_id,
        "provider_request_id_run_job": progresso.run_id,
        # R1-I3: o que o Google ACEITOU. Antes era `member_count` cru — o lote
        # inteiro, recusados inclusive.
        "members_submitted": members_submitted,
        "members_failed": len(progresso.membros_recusados),
        "failures": progresso.membros_recusados,
    }
