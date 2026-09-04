# bucket: always
"""Tool: apply_change - consume a confirmation token + execute the saved mutation.

Sprint 3b.26 introduces branching: operation_type=="import_offline_conversions" routes
to run_conversion_upload (ConversionUploadService); else routes to run_mutation
(GoogleAdsService.mutate).
"""

from typing import Any

import structlog

from src.db import connection
from src.google_ads.ad_schedule import (
    schedule_fingerprint,
    summarize_current,
    window_from_input,
)
from src.google_ads.conversions import run_conversion_upload
from src.google_ads.mutations import run_mutation
from src.google_ads.queries.ad_schedule import (
    GRADE_LIMIT,
    ad_schedule_query,
    parse_ad_schedule_row,
)
from src.google_ads.reports import run_report
from src.governance.dry_run import InvalidTokenError, consume
from src.mcp.context import get_current
from src.mcp.tools._mutate_common import error_envelope
from src.mcp.tools._registry import register_tool
from src.mcp.tools.get_ad_schedule import rows_to_current

log = structlog.get_logger(__name__)

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
        "[CORE] Confirma e aplica uma mutacao previamente previewed via dry-run. Token "
        "expira em 10 minutos. Cada token e consumivel apenas 1 vez e amarrado "
        "a sessao MCP que o gerou."
    ),
    input_schema=_SCHEMA,
    bucket="always",
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
        # Ruling 3 (ledger): estas chaves sao obrigatorias no payload (a tool sempre
        # grava); `.get(..., <default>)` seria o fallback calado que a Task 4 proibiu.
        campaign_ids = list(saved.payload["campaign_ids"])
        pedidas = {window_from_input(w).key() for w in saved.payload["windows"]}

        # Ruling 10 — concorrencia otimista. O que viaja no token e um DELTA calculado
        # ate 10 min antes, carregando resource_names observados naquele instante. Se a
        # grade mudou nesse meio tempo, aplicar o delta produz uma grade que nao e nem a
        # antiga nem a pedida — em silencio, porque partial_failure engole o erro por-op.
        # Este read e ANTES da escrita: se ele falhar, propagar e o lado seguro (nada
        # mutou ainda) — o tratamento best-effort do F83/F91 vale so depois da mutacao.
        rows_antes = await run_report(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=saved.customer_id,
            query=ad_schedule_query(campaign_ids=campaign_ids, status="enabled", limit=GRADE_LIMIT),
            row_formatter=parse_ad_schedule_row,
            operation_name="update_ad_schedule_precheck",
        )
        # Grade truncada aqui nao precisa de ramo proprio: o dry-run RECUSA acima de
        # GRADE_LIMIT, entao um fingerprint de 1001 linhas nunca bate com o guardado —
        # cai na divergencia abaixo, que e o lado seguro.
        if (
            schedule_fingerprint(rows_to_current(rows_antes), campaign_ids)
            != saved.payload["current_keys"]
        ):
            return error_envelope(
                "update_ad_schedule",
                "A grade mudou desde o preview (alguem alterou a agenda destas campanhas "
                "nos ultimos minutos). Nenhuma operacao foi aplicada. Refaca o "
                "update_ad_schedule para gerar um token novo sobre o estado atual.",
                customer_id=saved.customer_id,
            )

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
        # F83/F91: a mutacao ja aplicou (result acima e definitivo). A reconsulta e
        # I/O DEPOIS da escrita — se ela falhar (rede, GoogleAdsException transiente,
        # rate limit), isso nao pode transformar um sucesso em erro pro caller.
        resulting: dict[str, Any] | None
        confirmation_error: str | None = None
        try:
            # status="all" de proposito (spec §7): janela removida tem que ser
            # confirmada por PRESENCA de status REMOVED. Filtrar ENABLED confirmaria
            # a remocao por a linha NAO aparecer — exatamente o que a §7 proibe, e o
            # que a propria §7 estende "para a confirmacao que a tool faz pos-apply".
            rows = await run_report(
                manager_id=ctx.manager_id,
                session_id=ctx.session_id,
                customer_id=saved.customer_id,
                query=ad_schedule_query(campaign_ids=campaign_ids, status="all", limit=GRADE_LIMIT),
                row_formatter=parse_ad_schedule_row,
                operation_name="update_ad_schedule_confirm",
            )
            # O resumo (has_schedule/hours_per_week) conta so o que esta SERVINDO;
            # com status="all" nas linhas, somar REMOVED inflaria as horas.
            servindo = rows_to_current([r for r in rows if r["status"] == "ENABLED"])
            # summarize_current tambem devolve uma chave "windows" (contagem) — spread
            # primeiro e a lista de linhas por ultimo, senao o int pisa na lista.
            resulting = {
                cid: {
                    **summarize_current(servindo.get(cid, [])),
                    "windows": [r for r in rows if r["campaign_id"] == cid],
                    "matches_requested": {c.window.key() for c in servindo.get(cid, [])} == pedidas,
                }
                for cid in campaign_ids
            }
        except Exception as e:  # noqa: BLE001 — I/O apos escrita ja aplicada: nunca transformar sucesso em erro (F83/F91)
            log.warning(
                "update_ad_schedule_confirm_failed",
                customer_id=saved.customer_id,
                error=str(e),
                error_type=e.__class__.__name__,
            )
            resulting = None
            confirmation_error = (
                f"A mutacao foi aplicada (veja applied_count/provider_request_id), mas a "
                f"reconsulta da grade falhou ({e.__class__.__name__}). Confirme o estado "
                f"com get_ad_schedule antes de confiar no resultado."
            )
        return {
            "status": "applied",
            "operation": saved.operation_type,
            "customer_id": saved.customer_id,
            "blast_summary": saved.blast_summary,
            "provider_request_id": result["provider_request_id"],
            "applied_count": result["applied_count"],
            "changed_count": result.get("changed_count"),
            # Spec §4.5: "a resposta separa aplicadas de falhas, com o motivo de cada
            # falha". Lote com partial_failure=True e onde isso acontece.
            "partial_failures": result.get("partial_failures", []),
            "resource_names": result.get("resource_names", []),
            "resulting_schedule": resulting,
            "confirmation_error": confirmation_error,
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
