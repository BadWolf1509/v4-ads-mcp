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

from src.config import get_settings
from src.db import connection
from src.db.repositories import audit_log
from src.google_ads.client import build_client_for_manager
from src.google_ads.errors import to_friendly
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
) -> list[dict[str, Any]]:
    """Run a GAQL query against the given customer; return formatted rows.

    Raises:
        QuotaExhausted: if rate limit blocked
        GoogleAdsFriendlyError: if Google API errored (PT-BR message)
        NoOAuthConnectionError: if the manager has no OAuth connection
    """
    settings = get_settings()
    token_id = hash_developer_token(settings.google_ads_developer_token)
    started = time.monotonic()
    actual_ops = 0
    status = "success"
    error_message: str | None = None

    pool = connection.get_pool()
    results: list[dict[str, Any]] = []
    try:
        # Reserve quota
        async with pool.acquire() as conn:
            await before_call(conn, token_id, estimated_ops=estimated_ops)

        client = await build_client_for_manager(manager_id=manager_id)

        try:
            ga_service = client.get_service("GoogleAdsService")
            request = client.get_type("SearchGoogleAdsStreamRequest")
            request.customer_id = customer_id
            request.query = query

            stream = ga_service.search_stream(request=request)
            for batch in stream:
                actual_ops += 1
                for row in batch.results:
                    results.append(row_formatter(row))
        except Exception as e:
            raise to_friendly(e) from e

    except Exception as e:
        status = "error"
        error_message = str(e)
        raise
    finally:
        # Reconcile counter even on failure (we made API calls before erroring)
        async with pool.acquire() as conn:
            await record_actual(
                conn,
                token_id,
                actual_ops=actual_ops,
                estimated_ops=estimated_ops,
            )
            if audit_this_call:
                duration_ms = int((time.monotonic() - started) * 1000)
                await audit_log.record(
                    conn,
                    manager_id=manager_id,
                    session_id=session_id,
                    customer_id=customer_id,
                    action_type="read",
                    operation=operation_name,
                    target_count=len(results) if status == "success" else None,
                    params_summary=None,
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


async def execute_gaql_raw(
    *,
    manager_id: UUID,
    customer_id: str,
    query: str,
    estimated_ops: int = 1,
) -> list[dict[str, Any]]:
    """Run a GAQL query and return rows as plain dicts of field paths to values.

    Used by `run_gaql` utility tool; no formatter, no audit (audit is added by the
    tool itself since it's a sensitive escape hatch).
    """

    def _flatten(row: Any) -> dict[str, Any]:
        # Convert proto message to dict via google.protobuf.json_format
        from google.protobuf.json_format import MessageToDict  # type: ignore[import-untyped]

        return MessageToDict(row._pb, preserving_proto_field_name=True)  # type: ignore[no-any-return]

    return await run_report(
        manager_id=manager_id,
        session_id=manager_id,  # session_id used only for audit; ignored when audit_this_call=False
        customer_id=customer_id,
        query=query,
        row_formatter=_flatten,
        operation_name="run_gaql",
        estimated_ops=estimated_ops,
        audit_this_call=False,
    )
