# bucket: defer
"""Tool: validate_gaql - dry-run validate a GAQL query without consuming quota for data."""

import time
from typing import Any

from src.config import get_settings
from src.db import connection
from src.db.repositories import audit_log
from src.google_ads.access import ensure_account_access
from src.google_ads.client import build_client_for_manager
from src.google_ads.errors import to_friendly
from src.governance.bookkeeping import best_effort
from src.governance.rate_limit import (
    QuotaExhausted,
    before_call,
    hash_developer_token,
    record_actual,
)
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "query": {"type": "string", "minLength": 10},
    },
    "required": ["customer_id", "query"],
    "additionalProperties": False,
}


def _augment_error_hint(query: str, friendly_message: str) -> str:
    """Append contextual hints to common GAQL errors.

    Patterns catalogados via dogfood MO-JP 2026-05-19 (B2, B3):
    - B2: FROM change_event + erro de janela 30 dias.
    - B3: segments.conversion_action* + metrics.cost_micros incompativel.

    Mensagem original sempre preservada; hint apendado como `... | Hint: ...`.
    """
    if not query or not friendly_message:
        return friendly_message

    q = query.lower()
    m = friendly_message.lower()

    # B2: change_event resource tem janela maxima 30 dias inclusive.
    # LAST_30_DAYS abrange 31 dias (hoje + 30 anteriores) e e rejeitado.
    if "from change_event" in q and ("too old" in m or "older than 30 days" in m or "30 days" in m):
        return (
            friendly_message + " | Hint: change_event tem janela maxima de 30 dias inclusive — "
            "LAST_30_DAYS conta 31 dias e e rejeitado. Use LAST_14_DAYS ou "
            "date range explicito (start_date + end_date <= 30 dias)."
        )

    # B3: segments.conversion_action* + metrics.cost_micros conflito.
    # Google rejeita "unsupported metric" quando ambos no SELECT.
    if (
        "segments.conversion_action" in q
        and "metrics.cost_micros" in q
        and ("unsupported metric" in m or "unsupported metrics" in m)
    ):
        return (
            friendly_message
            + " | Hint: segments.conversion_action* nao combina com metrics.cost_micros "
            "no mesmo SELECT. Use 2 queries separadas: (1) conv por action com "
            "segments.conversion_action sem cost; (2) cost agregado por campaign "
            "sem segments."
        )

    return friendly_message


@register_tool(
    name="validate_gaql",
    description=(
        "[DEFER] Valida sintaxe + nomes de campos de um GAQL sem consumir quota de "
        "dados. Retorna {valid: bool, error: str|null}. Use antes de run_gaql "
        "pra evitar gastar quota com queries quebradas."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def validate_gaql(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    query = args["query"]

    # Hard-gate por conta (F57 class): valida o grant ANTES de tocar o client.
    # Sem isto, qualquer gestor validava GAQL contra qualquer conta da MCC,
    # vazando existência/schema da conta e bypassando o rate-limit. O denied
    # ja e auditado dentro de ensure_account_access -- nao duplicar aqui.
    # F91 — read pre-operacao, seguro de re-executar numa conexao nova.
    await connection.run_with_reconnect(
        lambda conn: ensure_account_access(
            conn,
            manager_id=ctx.manager_id,
            customer_id=customer_id,
            session_id=ctx.session_id,
            operation_name="validate_gaql",
            level="read",
        )
    )

    # Rate-limit no padrao 'reserved' de run_report (src/google_ads/reports.py,
    # commit 510cd9d): validate_only ainda conta na quota do Google, entao a
    # reserva precisa acontecer ANTES do search() -- antes desta task o gate
    # citava rate-limit como motivacao mas o rate-limit nao estava no caminho.
    settings = get_settings()
    token_id = hash_developer_token(settings.google_ads_developer_token)
    started = time.monotonic()
    estimated_ops = 1
    actual_ops = 0
    status = "success"
    error_message: str | None = None
    result: dict[str, Any] = {"valid": True, "error": None}

    pool = connection.get_pool()
    reserved = False
    try:
        # Transacao EXTERNA torna as duas reservas tudo-ou-nada (mesmo padrao
        # de run_report: before_call's conn.transaction() interna vira SAVEPOINT).
        async with pool.acquire() as conn, conn.transaction():
            await before_call(conn, token_id, estimated_ops=estimated_ops)
            await before_call(
                conn,
                f"mgr:{ctx.manager_id}",
                estimated_ops=estimated_ops,
                daily_limit=settings.manager_daily_quota,
            )
        reserved = True

        client = await build_client_for_manager(manager_id=ctx.manager_id)

        try:
            ga_service = client.get_service("GoogleAdsService")
            request = client.get_type("SearchGoogleAdsRequest")
            request.customer_id = customer_id
            request.query = query
            request.validate_only = True
            ga_service.search(request=request)
            actual_ops = 1
            result = {"valid": True, "error": None}
        except Exception as e:
            actual_ops = 1
            try:
                friendly = to_friendly(e)
                hinted = _augment_error_hint(query, friendly.message_pt)
                result = {"valid": False, "error": hinted, "code": friendly.code}
            except Exception:
                hinted = _augment_error_hint(query, str(e))
                result = {"valid": False, "error": hinted, "code": None}
            error_message = hinted
            status = "error"
    except QuotaExhausted as e:
        # Preserva a UX do tool (shape {valid, error}) em vez de propagar a
        # excecao crua pro caller MCP -- a mudanca aqui e so governanca.
        status = "error"
        error_message = str(e)
        result = {"valid": False, "error": str(e), "code": "QUOTA_EXHAUSTED"}
    except Exception as e:
        # Qualquer outra falha (ex.: build_client_for_manager sem OAuth) que nao
        # seja QuotaExhausted nem erro de validacao GAQL (esse ja e capturado e
        # convertido em result acima). Mesmo padrao de run_report: audita como
        # erro e re-propaga -- aqui NAO convertemos pro shape {valid, error}
        # porque nao e uma resposta de validacao, e uma falha de infraestrutura.
        status = "error"
        error_message = str(e)
        raise
    finally:
        # F83: best-effort e independentes — falha aqui descartaria o `result`
        # de uma validacao que ja rodou.
        if reserved:
            async with (
                best_effort(
                    "validate_gaql_quota_reconcile_failed",
                    operation="validate_gaql",
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
                    f"mgr:{ctx.manager_id}",
                    actual_ops=actual_ops,
                    estimated_ops=estimated_ops,
                )
        duration_ms = int((time.monotonic() - started) * 1000)
        async with (
            best_effort(
                "validate_gaql_audit_write_failed",
                operation="validate_gaql",
                customer_id=customer_id,
                status=status,
            ),
            pool.acquire() as conn,
        ):
            await audit_log.record(
                conn,
                manager_id=ctx.manager_id,
                session_id=ctx.session_id,
                customer_id=customer_id,
                action_type="read",
                operation="validate_gaql",
                params_summary={"query": query[:800], "valid": result["valid"]},
                status=status,
                error_message=error_message,
                duration_ms=duration_ms,
            )

    return result
