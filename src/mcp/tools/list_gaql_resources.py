# bucket: defer
"""Tool: list_gaql_resources - return the curated GAQL resource catalog."""

import time
from typing import Any

from src.config import get_settings
from src.db import connection
from src.db.repositories import audit_log
from src.google_ads import campos_gaql
from src.google_ads.access import ensure_account_access
from src.google_ads.queries.meta import RESOURCES, SEGMENTS
from src.governance.bookkeeping import best_effort
from src.governance.rate_limit import (
    CHAVE_COTA_PROJETO,
    QuotaExhausted,
    before_call,
    record_actual,
)
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "resource": {"type": "string", "pattern": "^[a-z_]+$"},
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
    },
    "additionalProperties": False,
}


def _catalogo() -> dict[str, Any]:
    return {
        "resources": [
            {
                "name": name,
                "description": meta["description"],
                "fields": meta["fields"],
            }
            for name, meta in RESOURCES.items()
        ],
        "segments": SEGMENTS,
    }


async def _compativel(
    resource: str, customer_id: str
) -> tuple[dict[str, list[str]] | None, str | None]:
    """(compativel, motivo). Falha nunca vira lista vazia: vira None + motivo."""
    ctx = get_current()
    # Hard-gate por conta ANTES de qualquer cache/quota/client (F57), em toda
    # chamada com `resource`. Negado: levanta e nada do Google e tocado.
    await connection.run_with_reconnect(
        lambda conn: ensure_account_access(
            conn,
            manager_id=ctx.manager_id,
            customer_id=customer_id,
            session_id=ctx.session_id,
            operation_name="list_gaql_resources",
            level="read",
        )
    )
    if (ja := campos_gaql.do_cache(resource)) is not None:
        return ja, None

    settings = get_settings()
    started = time.monotonic()
    pool = connection.get_pool()
    chave_gestor = f"mgr:{ctx.manager_id}"
    status = "success"
    error_message: str | None = None
    compativel: dict[str, list[str]] | None = None
    motivo: str | None = None
    reserved = False
    try:
        # Reserva tudo-ou-nada no molde do validate_gaql (1 operacao na quota).
        async with pool.acquire() as conn, conn.transaction():
            dia = await before_call(conn, CHAVE_COTA_PROJETO, estimated_ops=1)
            dia_do_gestor = await before_call(
                conn,
                chave_gestor,
                estimated_ops=1,
                daily_limit=settings.manager_daily_quota,
            )
        reserved = True
        compativel = await campos_gaql.compatibilidade(
            resource,
            manager_id=ctx.manager_id,
            customer_id=customer_id,
            session_id=ctx.session_id,
        )
        if compativel is None:
            motivo = f"O Google nao conhece o resource '{resource}' (GoogleAdsFieldService)."
    except QuotaExhausted as e:
        status, error_message = "error", str(e)
        motivo = f"Quota diaria esgotada, compatibilidade nao medida: {e}"
    except Exception as e:
        status, error_message = "error", str(e)
        motivo = f"Falha ao consultar o GoogleAdsFieldService: {e}"
    finally:
        if reserved:
            async with (
                best_effort(
                    "list_gaql_resources_quota_reconcile_failed",
                    operation="list_gaql_resources",
                ),
                pool.acquire() as conn,
                conn.transaction(),
            ):
                for chave, d in ((CHAVE_COTA_PROJETO, dia), (chave_gestor, dia_do_gestor)):
                    await record_actual(conn, chave, dia=d, actual_ops=1, estimated_ops=1)
        async with (
            best_effort(
                "list_gaql_resources_audit_write_failed",
                operation="list_gaql_resources",
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
                operation="list_gaql_resources",
                params_summary={"resource": resource, "compativel": compativel is not None},
                status=status,
                error_message=error_message,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
    return compativel, motivo


@register_tool(
    name="list_gaql_resources",
    description=(
        "[DEFER] Catalogo curado de resources GAQL (15+) com seus campos comumente usados. "
        "Inclui tambem a lista de segments aplicaveis. Use junto com run_gaql ou "
        "validate_gaql pra construir queries customizadas. Com `resource` (ex.: keyword_view; exige `customer_id`, "
        "que passa pelo gate de acesso) devolve tambem `compativel` {segments, metrics, resources_atribuidos} lido do "
        "GoogleAdsFieldService (selectable_with; 1 operacao de quota, cacheado), com `fonte` "
        "e `compativel_motivo`; `compativel` null = nao foi possivel medir (veja o motivo), "
        "nunca lista vazia."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def list_gaql_resources(args: dict[str, Any]) -> dict[str, Any]:
    resposta = _catalogo()
    resource = args.get("resource")
    if resource is None:
        return resposta
    customer_id = args.get("customer_id")
    if not customer_id:
        return {
            "error": (
                "informe customer_id: a consulta de compatibilidade passa pelo gate "
                "de acesso da conta"
            ),
            "code": "CUSTOMER_ID_OBRIGATORIO",
        }
    compativel, motivo = await _compativel(resource, customer_id)
    resposta["compativel"] = compativel
    resposta["fonte"] = campos_gaql.FONTE
    resposta["compativel_motivo"] = motivo
    return resposta
