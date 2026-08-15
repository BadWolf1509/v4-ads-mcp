"""Shared executor for Meta Graph API GET requests.

Mirror semantics of src/google_ads/reports.py:
- Rate limit post-call only (Meta tem BUC header, sem global counter pre-flight)
- Audit log opt-in (sensitive reads, mutates)
- PT-BR errors via to_friendly_meta_error()

V0 (Sprint M.2a) covers simple GET edges (/me/adaccounts etc).
M.3+ adds Insights API support (paginação, async jobs).
"""

import time
from typing import Any, cast
from uuid import UUID

import structlog

from src.config import get_settings
from src.db import connection
from src.db.repositories import audit_log, manager_meta_account_access
from src.governance.rate_limit import record_actual_meta
from src.meta_ads.client import MetaAccessDeniedError, build_meta_api
from src.meta_ads.errors import to_friendly_meta_error

log = structlog.get_logger(__name__)


async def run_meta_graph_get(
    *,
    manager_id: UUID,
    session_id: UUID,
    ad_account_id: str,
    edge: str,
    params: dict[str, Any] | None = None,
    operation_name: str,
    estimated_calls: int = 1,
    max_pages: int = 1,
    audit_this_call: bool = False,
    params_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute Meta Graph API GET; parse BUC header; record audit + rate counters.

    Args:
        manager_id: bind context manager UUID
        session_id: bind context MCP session UUID
        ad_account_id: conta Meta (act_<id>) sendo acessada. Kwarg OBRIGATÓRIO —
            o hard-gate sempre roda contra ele. Antes era lido de params.get(),
            um fail-open: um tool que montasse o edge e esquecesse o param passava
            SEM gate (classe F57 no lado Meta). Agora é impossível pular (F72).
        edge: Graph API edge path, e.g., "/me/adaccounts"
        params: query parameters dict
        operation_name: for audit log + rate limit operation field
        estimated_calls: how many API calls this counts as
        max_pages: quantas páginas seguir via `paging.next` (F88). Default 1
            preserva o comportamento antigo pros callers que leem 1 objeto só
            (ex.: overview). Edges de coleção passam >1: sem isso, a resposta é a
            1ª página e quem ordena depois ordena uma amostra enviesada — o
            "top por gasto" deixa de ser o top. O `paging` da ÚLTIMA página é
            preservado no retorno, então o caller sabe se ficou dado pra trás.
        audit_this_call: opt-in audit (sensitive reads, mutates)
        params_summary: optional dict embedded in audit_log.params_summary

    Returns:
        Parsed JSON response body (dict with "data" key for collection edges).

    Raises:
        MetaAccessDeniedError: manager sem grant na ad account (hard-gate)
        MetaSystemUserTokenMissingError: secret meta-system-user-token não configurado
        MetaAdsFriendlyError: friendly PT-BR error wrapping Meta API failures
    """
    settings = get_settings()

    # Hard-gate (Modelo B): manager precisa de grant na conta. O token é compartilhado,
    # então a matriz manager_meta_account_access é o ÚNICO freio. INCONDICIONAL —
    # ad_account_id é kwarg obrigatório, então nenhum caminho pula o gate (F72).
    async with connection.get_pool().acquire() as conn:
        allowed = await manager_meta_account_access.can_manager_access(
            conn, manager_id, ad_account_id, level="read"
        )
        if not allowed:
            # Negação de acesso é SEMPRE auditada (evento de segurança),
            # independente do audit_this_call opt-in — espelha o gate Google
            # (ensure_account_access sempre grava denied). M.4/M.5 trarão tools
            # Meta com audit_this_call=False; sem isto, suas negações ficariam
            # invisíveis no audit_log.
            await audit_log.record(
                conn,
                manager_id=manager_id,
                session_id=session_id,
                customer_id=ad_account_id,
                action_type="read",
                operation=operation_name,
                params_summary=params_summary,
                status="denied",
                error_message="Gestor sem acesso à conta Meta",
                platform="meta",
            )
            log.warning(
                "meta_account_access_denied",
                manager_id=str(manager_id),
                ad_account_id=ad_account_id,
                operation=operation_name,
                platform="meta",
            )
            raise MetaAccessDeniedError(
                f"Você não tem acesso à conta {ad_account_id}. Peça ao admin pra liberar no painel."
            )

    api = build_meta_api(
        system_user_token=settings.meta_system_user_token,
        app_id=settings.meta_app_id,
        app_secret=settings.meta_app_secret,
    )

    log.info("meta_graph_get_start", edge=edge, operation=operation_name)
    started = time.monotonic()

    try:
        # F88: segue `paging.next` até `max_pages`. As linhas de todas as páginas
        # são concatenadas em `data`; o `paging` que sobrevive é o da ÚLTIMA
        # página, então um `next` remanescente sinaliza truncamento pro caller.
        body = cast(dict[str, Any], {})
        linhas: list[Any] = []
        paginas_lidas = 0
        proxima_url: str | None = None
        while paginas_lidas < max_pages:
            if proxima_url is None:
                response = api.call("GET", [edge.lstrip("/")], params=params or {})
            else:
                # `paging.next` já carrega cursor + fields + token na própria URL.
                response = api.call("GET", [proxima_url], params={})
            body = cast(dict[str, Any], response.json())
            paginas_lidas += 1
            linhas.extend(body.get("data") or [])
            proxima_url = (body.get("paging") or {}).get("next")
            if not proxima_url:
                break
        if "data" in body or linhas:
            body = {**body, "data": linhas}
    except Exception as e:  # noqa: BLE001 — catch all to map to friendly
        elapsed_ms = int((time.monotonic() - started) * 1000)
        friendly = to_friendly_meta_error(e)
        if audit_this_call:
            async with connection.get_pool().acquire() as conn:
                await audit_log.record(
                    conn,
                    manager_id=manager_id,
                    session_id=session_id,
                    customer_id=(params_summary or {}).get("ad_account_id"),
                    action_type="read",
                    operation=operation_name,
                    params_summary=params_summary,
                    status="error",
                    error_message=friendly.message,
                    duration_ms=elapsed_ms,
                    platform="meta",
                )
        log.warning(
            "meta_graph_get_error",
            edge=edge,
            operation=operation_name,
            error=friendly.message,
            duration_ms=elapsed_ms,
        )
        raise friendly from e

    elapsed_ms = int((time.monotonic() - started) * 1000)

    # Post-call rate counter update from BUC header. `ad_account_id` é o kwarg
    # OBRIGATÓRIO desta função (pós-F72, sempre presente) — não mais lido de
    # params.get("ad_account_id"), que era um passthrough espúrio só existindo
    # pra alimentar este contador (Task 3.4: desacopla o BUC do dict de params
    # do Graph, que agora pode perder essa chave sem quebrar o rate counter).
    buc_header = response.headers().get("x-business-use-case-usage")
    if buc_header:
        try:
            await record_actual_meta(
                app_id=settings.meta_app_id,
                ad_account_id=ad_account_id,
                buc_header=buc_header,
                # F88: contabiliza as chamadas REALMENTE feitas, não a estimativa.
                calls=max(estimated_calls, paginas_lidas),
            )
        except Exception as e:  # noqa: BLE001
            log.warning("meta_rate_counter_update_failed", error=str(e))

    if audit_this_call:
        async with connection.get_pool().acquire() as conn:
            await audit_log.record(
                conn,
                manager_id=manager_id,
                session_id=session_id,
                customer_id=(params_summary or {}).get("ad_account_id"),
                action_type="read",
                operation=operation_name,
                target_count=len(body.get("data", [])) if isinstance(body, dict) else None,
                params_summary=params_summary,
                status="success",
                duration_ms=elapsed_ms,
                platform="meta",
                provider_request_id=response.headers().get("x-fb-trace-id"),
            )

    log.info(
        "meta_graph_get_done",
        edge=edge,
        operation=operation_name,
        duration_ms=elapsed_ms,
    )
    return body
