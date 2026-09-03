# bucket: defer
"""Tool: apply_change - consume a confirmation token + execute the saved mutation.

Sprint 3b.26 introduces branching: operation_type=="import_offline_conversions" routes
to run_conversion_upload (ConversionUploadService); else routes to run_mutation
(GoogleAdsService.mutate).
"""

from typing import Any

from src.db import connection
from src.google_ads.ad_schedule import summarize_current
from src.google_ads.conversions import run_conversion_upload
from src.google_ads.mutations import run_mutation
from src.google_ads.queries.ad_schedule import ad_schedule_query, parse_ad_schedule_row
from src.google_ads.reports import run_report
from src.governance.dry_run import InvalidTokenError, consume
from src.mcp.context import get_current
from src.mcp.tools._mutate_common import error_envelope
from src.mcp.tools._registry import register_tool
from src.mcp.tools.get_ad_schedule import rows_to_current

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "confirmation_token": {
            "type": "string",
            "pattern": "^[A-Z0-9]{8}$",
            "description": "Token de 8 chars retornado por uma tool de mutacao em modo dry-run.",
        },
    },
    "required": ["confirmation_token"],
    "additionalProperties": False,
}


@register_tool(
    name="apply_change",
    description=(
        "[DEFER] Confirma e aplica uma mutacao previamente previewed via dry-run. Token "
        "expira em 10 minutos. Cada token e consumivel apenas 1 vez e amarrado "
        "a sessao MCP que o gerou."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def apply_change(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    token = args["confirmation_token"]

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        try:
            saved = await consume(conn, token=token, session_id=ctx.session_id)
        except InvalidTokenError as e:
            return error_envelope("apply_change", str(e))

    target_count = int(saved.payload.get("__target_count__", 1))
    params_summary = saved.payload.get("__params_summary__")  # None → default in dispatchers

    # Sprint 3b.26: branch dispatch based on operation_type.
    if saved.operation_type == "import_offline_conversions":
        # ConversionUploadService path (NOT GoogleAdsService.mutate).
        result = await run_conversion_upload(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=saved.customer_id,
            operation_type=saved.operation_type,
            payload=saved.payload,
            target_count=target_count,
            params_summary=params_summary,
        )
        # If error from dispatcher, return as-is.
        if result.get("status") == "error":
            return result
        # Conversion upload response — different shape from mutation response.
        return {
            "status": "applied",
            "operation": saved.operation_type,
            "customer_id": saved.customer_id,
            "blast_summary": saved.blast_summary,
            "provider_request_id": result["provider_request_id"],
            "applied_count": result["applied_count"],
            "failed_count": result["failed_count"],
            "failures": result["failures"],
        }

    # Sprint 3b.28: OfflineUserDataJobService path (Customer Match upload).
    if saved.operation_type == "upload_customer_match_list":
        from src.google_ads.customer_match import run_offline_user_data_job

        result = await run_offline_user_data_job(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=saved.customer_id,
            user_list_id=saved.payload["user_list_id"],
            operation_type=saved.payload["operation"],
            hashed_members=saved.payload["hashed_members"],
        )
        job_id = result["job_resource_name"].rsplit("/", 1)[-1]
        return {
            "status": "submitted",
            "operation": "upload_customer_match_list",
            "customer_id": saved.customer_id,
            "user_list_id": saved.payload["user_list_id"],
            "operation_type": saved.payload["operation"],
            "members_submitted": result["members_submitted"],
            "job_resource_name": result["job_resource_name"],
            "provider_request_id_create_job": result["provider_request_id_create_job"],
            "provider_request_id_add_ops": result["provider_request_id_add_ops"],
            "provider_request_id_run_job": result["provider_request_id_run_job"],
            "to_check_status": (
                f"Job é assíncrono no backend Google (processa em horas). "
                f"Pra verificar status, use run_gaql com query 'SELECT "
                f"offline_user_data_job.status, offline_user_data_job."
                f"failure_reason FROM offline_user_data_job WHERE "
                f"offline_user_data_job.id = {job_id}'."
            ),
        }

    # ad_schedule §4.6: confirmacao de estado por GAQL. A UI falhou em silencio duas
    # vezes nessa conta; confiar no ACK da mutacao repetiria o problema num canal novo.
    if saved.operation_type == "update_ad_schedule":
        result = await run_mutation(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=saved.customer_id,
            operation_type=saved.operation_type,
            payload=saved.payload,
            target_count=target_count,
            partial_failure=True,
            params_summary=params_summary,
        )
        # Ruling 3 (ledger): a lista e obrigatoria no payload (Task 7 sempre grava);
        # `.get(..., [])` seria o fallback calado que a Task 4 acabou de proibir —
        # com [] os builders levantam ValueError DEPOIS da mutacao ja aplicada.
        campaign_ids = list(saved.payload["campaign_ids"])
        rows = await run_report(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=saved.customer_id,
            query=ad_schedule_query(campaign_ids=campaign_ids, status="enabled", limit=1000),
            row_formatter=parse_ad_schedule_row,
            operation_name="update_ad_schedule_confirm",
        )
        atual = rows_to_current(rows)
        # summarize_current tambem devolve uma chave "windows" (contagem) — spread
        # primeiro e a lista de linhas por ultimo, senao o int pisa na lista.
        resulting = {
            cid: {
                **summarize_current(atual.get(cid, [])),
                "windows": [r for r in rows if r["campaign_id"] == cid],
            }
            for cid in campaign_ids
        }
        return {
            "status": "applied",
            "operation": saved.operation_type,
            "customer_id": saved.customer_id,
            "blast_summary": saved.blast_summary,
            "provider_request_id": result["provider_request_id"],
            "applied_count": result["applied_count"],
            "changed_count": result.get("changed_count"),
            "resource_names": result.get("resource_names", []),
            "resulting_schedule": resulting,
        }

    # Default path: chained mutation via GoogleAdsService.mutate (Sprint 3b.1-3b.25).
    partial_failure = bool(saved.payload.get("__partial_failure__", False))
    result = await run_mutation(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=saved.customer_id,
        operation_type=saved.operation_type,
        payload=saved.payload,
        target_count=target_count,
        partial_failure=partial_failure,
        params_summary=params_summary,
    )
    return {
        "status": "applied",
        "operation": saved.operation_type,
        "customer_id": saved.customer_id,
        "blast_summary": saved.blast_summary,
        "provider_request_id": result["provider_request_id"],
        "applied_count": result["applied_count"],
        # F139: quantos de fato mudaram. `applied_count` conta o tentado, entao
        # numa re-remocao ele diz 1 para uma operacao que nao mudou nada.
        "changed_count": result.get("changed_count"),
        "resource_names": result.get("resource_names", []),
    }
