"""Shared executor for Meta Graph API GET requests.

Mirror semantics of src/google_ads/reports.py:
- Rate limit post-call only (Meta tem BUC header, sem global counter pre-flight)
- Audit log opt-in (sensitive reads, mutates)
- PT-BR errors via to_friendly_meta_error()

V0 (Sprint M.2a) covers simple GET edges (/me/adaccounts etc).
M.3+ adds Insights API support (paginação, async jobs).
"""

import time
from typing import Any
from uuid import UUID

import httpx
import structlog

from src.config import get_settings
from src.db import connection
from src.db.repositories import audit_log, manager_meta_account_access
from src.governance.bookkeeping import best_effort
from src.governance.rate_limit import record_actual_meta
from src.meta_ads.client import (
    META_GRAPH_API_VERSION,
    MetaAccessDeniedError,
    MetaSystemUserTokenMissingError,
)
from src.meta_ads.errors import to_friendly_meta_error

log = structlog.get_logger(__name__)

# F190 — timeout explicito. O SDK que saiu daqui guardava `timeout=None` e
# repassava a `requests`, que bloqueia indefinidamente; como a chamada ia por
# `run_blocking`, uma conexao pendurada prendia um slot do pool de threads do
# anyio, compartilhado com os cinco executores Google. Espelha o valor que os
# outros call sites Meta em httpx ja usam (`auth/meta_oauth.py`).
_TIMEOUT_GRAPH = 30.0


class MetaGraphHTTPError(Exception):
    """Status HTTP nao-2xx da Graph API, com o codigo no texto.

    Existe porque `FacebookResponse.is_success()` decidia sucesso por teste de
    SUBSTRING sobre o corpo: uma pagina HTML de erro de intermediario passava, e
    o estouro chegava ao gestor como `'str' object has no attribute 'get'`,
    marcado como permanente. Agora o status e o veredito.
    """

    def __init__(self, status: int, trecho: str):
        self.status = status
        self.retryable = status >= 500 or status == 429
        super().__init__(f"Graph API respondeu HTTP {status}: {trecho}")


async def _paginar_graph(
    http: httpx.AsyncClient,
    url: str,
    params: dict[str, Any],
    cabecalhos: dict[str, str],
    max_pages: int,
) -> tuple[dict[str, Any], list[Any], httpx.Headers, int]:
    """Segue `paging.next` ate `max_pages`.

    Devolve `(ultimo_corpo, linhas, headers, paginas_lidas)`. O `paging` que
    sobrevive e o da ULTIMA pagina lida — e assim que o chamador sabe se ficou
    dado para tras. Os headers da ultima resposta saem junto porque o contador
    BUC os le. `paginas_lidas` e o numero de requests REALMENTE feitos: o
    rate counter (BUC) conta chamadas de verdade, nao a estimativa do caller
    (F88) — sem isto o contador ficaria impreciso pro primeiro caller que
    setar `max_pages > 1` (hoje nenhum seta; _MAX_PAGES das tools Meta e 1).

    F189: a URL do `next` vai como STRING. Foi embrulhada em lista uma vez, e o
    SDK — que so trata string como URL completa — concatenou na base e produziu
    uma URL dobrada; qualquer resultado com mais de uma pagina virava erro.
    """
    linhas: list[Any] = []
    corpo: dict[str, Any] = {}
    proxima: str | None = None
    headers = httpx.Headers()
    lidas = 0
    for _ in range(max_pages):
        if proxima is None:
            resp = await http.get(url, params=params, headers=cabecalhos)
        else:
            # `paging.next` ja carrega cursor e fields na propria URL.
            resp = await http.get(proxima, headers=cabecalhos)
        headers = resp.headers
        if resp.status_code != 200:
            raise MetaGraphHTTPError(resp.status_code, resp.text[:200])
        bruto = resp.json()
        if not isinstance(bruto, dict):
            # Nao e `cast`: o cast satisfaz o mypy e nao existe em runtime.
            raise MetaGraphHTTPError(resp.status_code, f"corpo nao-JSON: {type(bruto).__name__}")
        corpo = bruto
        lidas += 1
        linhas.extend(corpo.get("data") or [])
        proxima = (corpo.get("paging") or {}).get("next")
        if not proxima:
            break
    return corpo, linhas, headers, lidas


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
            O audit também sai daqui, não de `params_summary`: aquele dict é
            opcional, então um caller que esquecesse a chave gravava a linha com
            conta NULA — na plataforma onde o token é compartilhado e a matriz é
            o único freio, é a última linha que pode ficar sem a conta.
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
    # F91 — a checagem é read idempotente e roda a CADA request; vai por
    # `run_with_reconnect` (conexão ociosa que o Supabase fechou não pode
    # derrubar o único freio do Modelo B). O audit da negação fica FORA: é
    # write, e retry cego duplicaria a linha.
    allowed = await connection.run_with_reconnect(
        lambda conn: manager_meta_account_access.can_manager_access(
            conn, manager_id, ad_account_id, level="read"
        )
    )
    if not allowed:
        # Negação de acesso é SEMPRE auditada (evento de segurança),
        # independente do audit_this_call opt-in — espelha o gate Google
        # (ensure_account_access sempre grava denied). M.4/M.5 trarão tools
        # Meta com audit_this_call=False; sem isto, suas negações ficariam
        # invisíveis no audit_log.
        async with (
            best_effort(
                "meta_account_access_denial_audit_failed",
                manager_id=str(manager_id),
                ad_account_id=ad_account_id,
                operation=operation_name,
            ),
            connection.get_pool().acquire() as conn,
        ):
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

    token = settings.meta_system_user_token
    if not token:
        raise MetaSystemUserTokenMissingError(
            "Token do system user Meta não configurado. "
            "O admin precisa subir o secret meta-system-user-token."
        )

    log.info("meta_graph_get_start", edge=edge, operation=operation_name)
    started = time.monotonic()

    try:
        # F190 — token no HEADER, nunca na query. Mesma postura de
        # `graph.py::fetch_paginated`, que ja rodava assim em producao: e a
        # evidencia empirica de que este app nao exige `appsecret_proof`.
        cabecalhos = {"Authorization": f"Bearer {token}"}
        url = f"https://graph.facebook.com/{META_GRAPH_API_VERSION}{edge}"
        async with httpx.AsyncClient(timeout=_TIMEOUT_GRAPH) as http:
            body, linhas, headers_ultima, paginas_lidas = await _paginar_graph(
                http, url, params or {}, cabecalhos, max_pages
            )
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
                    customer_id=ad_account_id,
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
    buc_header = headers_ultima.get("x-business-use-case-usage")
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
                customer_id=ad_account_id,
                action_type="read",
                operation=operation_name,
                target_count=len(body.get("data", [])) if isinstance(body, dict) else None,
                params_summary=params_summary,
                status="success",
                duration_ms=elapsed_ms,
                platform="meta",
                provider_request_id=headers_ultima.get("x-fb-trace-id"),
            )

    log.info(
        "meta_graph_get_done",
        edge=edge,
        operation=operation_name,
        duration_ms=elapsed_ms,
    )
    return body
