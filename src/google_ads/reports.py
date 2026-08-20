"""Shared executor for read-only report tools.

Each report tool calls `run_report` with:
  - the manager context (from MCP middleware)
  - a customer_id to query
  - a GAQL query string
  - an optional row_formatter to shape SDK rows into JSON-serializable dicts

run_report handles the boilerplate:
  - rate limit: before_call -> record_actual
  - build the client per manager
  - execute search_stream over the GAQL
  - call the formatter on each row
  - return the list

Audit logging is OPTIONAL per call (volume reads skip it; sensitive reads opt in).
"""

import time
from collections.abc import Callable
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
from src.governance.bookkeeping import best_effort
from src.governance.rate_limit import (
    before_call,
    hash_developer_token,
    record_actual,
)

log = structlog.get_logger(__name__)


async def run_report(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    query: str,
    row_formatter: Callable[[Any], dict[str, Any]],
    operation_name: str,
    estimated_ops: int = 1,
    audit_this_call: bool = False,
    params_summary: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run a GAQL query against the given customer; return formatted rows.

    Raises:
        QuotaExhausted: if rate limit blocked
        GoogleAdsFriendlyError: if Google API errored (PT-BR message)
        NoOAuthConnectionError: if the manager has no OAuth connection
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
            operation_name=operation_name,
            level="read",
        )
    )
    token_id = hash_developer_token(settings.google_ads_developer_token)
    started = time.monotonic()
    actual_ops = 0
    status = "success"
    error_message: str | None = None

    pool = connection.get_pool()
    results: list[dict[str, Any]] = []
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

        try:
            ga_service = client.get_service("GoogleAdsService")
            request = client.get_type("SearchGoogleAdsStreamRequest")
            request.customer_id = customer_id
            request.query = query

            # F86: a chamada E o consumo do stream saem do event loop. Offloadar
            # só o `search_stream` não adiantaria — ele devolve um iterador cuja
            # I/O acontece no `for`, então o bloqueio só mudaria de lugar.
            def _consumir_stream() -> tuple[int, list[dict[str, Any]]]:
                lidos = 0
                linhas: list[dict[str, Any]] = []
                for batch in ga_service.search_stream(request=request):
                    lidos += 1
                    for row in batch.results:
                        linhas.append(row_formatter(row))
                return lidos, linhas

            batches, linhas = await run_blocking(_consumir_stream)
            actual_ops += batches
            results.extend(linhas)
        except Exception as e:
            raise to_friendly(e) from e

    except Exception as e:
        status = "error"
        error_message = str(e)
        raise
    finally:
        # Reconcile counters even on failure (we made API calls before erroring) —
        # SO se a reserva foi persistida (reserved=True). Sem reserva nao ha nada
        # pra reconciliar; reconciliar mesmo assim decrementaria o contador sem
        # contrapartida (F73 — o quota leak original).
        # F83: best-effort e independentes — falha de conexao aqui descartaria o
        # `return` de um relatorio ja lido com sucesso.
        if reserved:
            async with (
                best_effort(
                    "report_quota_reconcile_failed",
                    operation=operation_name,
                    customer_id=customer_id,
                ),
                pool.acquire() as conn,
                conn.transaction(),
            ):
                await record_actual(
                    conn,
                    token_id,
                    actual_ops=actual_ops,
                    estimated_ops=estimated_ops,
                )
                await record_actual(
                    conn,
                    f"mgr:{manager_id}",
                    actual_ops=actual_ops,
                    estimated_ops=estimated_ops,
                )
        # O `if` vem ANTES do acquire: sem opt-in de audit nao ha por que pegar
        # conexao (era um ponto de falha gratuito dentro do finally).
        if audit_this_call:
            async with (
                best_effort(
                    "report_audit_write_failed",
                    operation=operation_name,
                    customer_id=customer_id,
                    status=status,
                ),
                pool.acquire() as conn,
            ):
                duration_ms = int((time.monotonic() - started) * 1000)
                await audit_log.record(
                    conn,
                    manager_id=manager_id,
                    session_id=session_id,
                    customer_id=customer_id,
                    action_type="read",
                    operation=operation_name,
                    target_count=len(results) if status == "success" else None,
                    params_summary=params_summary,
                    status=status,
                    error_message=error_message,
                    duration_ms=duration_ms,
                )

    log.info(
        "report_complete",
        operation=operation_name,
        customer_id=customer_id,
        rows=len(results),
        ops=actual_ops,
    )
    return results


async def lookup_country_names(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    country_ids: set[str],
) -> dict[str, dict[str, str]]:
    """Resolve country_criterion_ids -> {name, country_code} via geo_target_constant.

    geo_target_constant is global Google Ads metadata (not per-customer data),
    but the query still goes through a customer endpoint -- we reuse the same
    customer_id the caller used. Returns empty dict on empty input. IDs not
    returned by Google are absent from the result; callers decide the fallback.

    Cost: typically 1 op (a single small batch).
    """
    if not country_ids:
        return {}
    # Country IDs come from row formatters as digit strings. Sort for query
    # stability (helps caching/debugging). Embed directly as integers in the
    # IN clause; geo_target_constant.id is int64 in GAQL.
    ids_clause = ",".join(sorted(country_ids))
    query = (
        "SELECT geo_target_constant.id, geo_target_constant.name, "
        "geo_target_constant.country_code "
        "FROM geo_target_constant "
        f"WHERE geo_target_constant.id IN ({ids_clause})"
    )

    def _format(row: Any) -> dict[str, Any]:
        gtc = row.geo_target_constant
        return {
            "id": str(gtc.id),
            "name": str(gtc.name),
            "country_code": str(gtc.country_code),
        }

    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_format,
        operation_name="lookup_country_names",
        audit_this_call=False,
    )
    return {r["id"]: {"name": r["name"], "country_code": r["country_code"]} for r in rows}


async def execute_gaql_raw(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    query: str,
    limit: int,
    estimated_ops: int = 1,
) -> list[dict[str, Any]]:
    """Run a GAQL query and return rows as plain dicts of field paths to values.

    Used by `run_gaql` utility tool; no formatter. Always audited — run_gaql is
    a sensitive escape hatch and every successful call must appear in the audit
    log WITH the query that ran (Task 1.3: params_summary was None before,
    leaving the audit trail empty despite audit_this_call=True).
    """

    def _flatten(row: Any) -> dict[str, Any]:
        # Convert proto message to dict via google.protobuf.json_format
        from google.protobuf.json_format import MessageToDict

        return MessageToDict(row._pb, preserving_proto_field_name=True)  # type: ignore[no-any-return]

    return await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_flatten,
        operation_name="run_gaql",
        estimated_ops=estimated_ops,
        audit_this_call=True,
        params_summary={"query": query[:800], "limit": limit},
    )
