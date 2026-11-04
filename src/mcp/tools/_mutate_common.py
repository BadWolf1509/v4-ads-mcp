# bucket: n/a (helper module, not a tool)
"""Helpers de envelope compartilhados pelos tools de mutate (dry-run/apply/error).

Centraliza o bloco "risk -> AUTO-apply / dry-run / error" que estava copiado
em 22 tools (~900 linhas), incluindo o literal `expires_in_minutes: 10`
hardcoded (agora usa DEFAULT_TTL_MINUTES de src/governance/dry_run.py).

Canoniza o envelope de erro: chave `error_message` (não `error`), alinhado
com `_error_envelope` de src/mcp/server.py e os tools Meta. `operation`
está sempre presente no envelope de erro.
"""

from typing import Any

from src.db import connection
from src.governance.blast_radius import RiskClassification
from src.governance.dry_run import DEFAULT_TTL_MINUTES, create_pending

_APPLY_HINT = "Chame apply_change(confirmation_token=<token>) para aplicar."


def error_envelope(
    operation: str,
    message: str,
    *,
    customer_id: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Envelope canônico de erro: status=error + error_message + operation.

    `customer_id` só entra se fornecido (alguns call-sites de erro pré-flight
    ainda não resolveram customer_id, ex: update_campaign_budget lookup miss).
    `**extra` carrega campos por-tool (missing_ids, negative_ids_blocked, etc —
    tipicamente vindos de um dict de pré-flight de _common.py que usava a
    chave `error`; o call site deve popar essa chave antes de repassar aqui).
    """
    result: dict[str, Any] = {"status": "error", "error_message": message, "operation": operation}
    if customer_id is not None:
        result["customer_id"] = customer_id
    result.update(extra)
    return result


def applied_envelope(
    operation: str,
    customer_id: str,
    blast_summary: str,
    *,
    applied_count: int,
    provider_request_id: str,
    auto_applied_reason: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Envelope canônico de sucesso de mutate (status=applied).

    Serve os DOIS caminhos de sucesso: o AUTO-apply (a tool decidiu aplicar sem
    confirmação, e `auto_applied_reason` diz por quê) e o de CONFIRMAÇÃO (o
    `apply_change` executando o que o gestor confirmou). No segundo não existe
    razão de auto-aplicação, e inventar uma afirmaria que a tool decidiu
    sozinha — por isso o campo é opcional e **só entra quando não-None**,
    espelhando o `confirmation_reason` do `preview_envelope`.

    O que o helper garante em toda resposta de sucesso: `status`, `operation`,
    `customer_id`, `blast_summary`, `applied_count`, `provider_request_id`.
    Enquanto 5 tools montavam esse dict à mão, uma delas
    (`add_negatives_from_search_terms`) simplesmente não devolvia
    `blast_summary` — e nada ficava vermelho, porque cada envelope à mão é um
    contrato próprio.

    `**extra` carrega campos por-tool (changes[], added[], attachments_result[],
    resource_names, partial_failures, etc).
    """
    result: dict[str, Any] = {
        "status": "applied",
        "operation": operation,
        "customer_id": customer_id,
        "blast_summary": blast_summary,
        "applied_count": applied_count,
        "provider_request_id": provider_request_id,
    }
    if auto_applied_reason is not None:
        result["auto_applied_reason"] = auto_applied_reason
    result.update(extra)
    return result


def submitted_envelope(
    operation: str,
    customer_id: str,
    blast_summary: str,
    **extra: Any,
) -> dict[str, Any]:
    """Envelope canônico de trabalho ACEITO mas ainda não concluído (status=submitted).

    Existe um caso: o Customer Match, cujo `OfflineUserDataJob` o Google
    processa em horas — dizer `applied` ali afirmaria um resultado que ninguém
    ainda tem. O núcleo garantido é o mesmo do `applied_envelope` menos
    `applied_count`/`provider_request_id`, que não existem nessa forma (o job
    tem TRÊS request-ids, um por passo).

    `blast_summary` entra por construção pelo mesmo motivo dos outros
    envelopes: o gestor confirmou um token cujo resumo dizia o que ia
    acontecer, e a resposta tem que ecoar isso — o envelope à mão que este
    helper substitui não devolvia o campo.
    """
    result: dict[str, Any] = {
        "status": "submitted",
        "operation": operation,
        "customer_id": customer_id,
        "blast_summary": blast_summary,
    }
    result.update(extra)
    return result


def preview_envelope(
    operation: str,
    customer_id: str,
    blast_summary: str,
    token: str,
    *,
    confirmation_reason: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Envelope canônico de dry-run (status=dry_run) com confirmation_token.

    `expires_in_minutes` usa DEFAULT_TTL_MINUTES (nao mais o literal 10
    hardcoded 22x). `confirmation_reason` só entra se não-None (bulk_pause_by_query
    omite por design — não chama blast_radius.classify). `**extra` carrega campos
    por-tool (preview{}, changes[], *_preview[], sample_keywords, etc).
    """
    result: dict[str, Any] = {
        "status": "dry_run",
        "operation": operation,
        "customer_id": customer_id,
        "blast_summary": blast_summary,
        "confirmation_token": token,
        "expires_in_minutes": DEFAULT_TTL_MINUTES,
        "to_apply": _APPLY_HINT,
    }
    if confirmation_reason is not None:
        result["confirmation_reason"] = confirmation_reason
    result.update(extra)
    return result


async def emitir_preview(
    ctx: Any,
    *,
    operation: str,
    customer_id: str,
    payload: dict[str, Any],
    summary: str,
    risk: RiskClassification,
    **extra: Any,
) -> dict[str, Any]:
    """Grava a pendencia e devolve o envelope de dry-run — o bloco que 20 tools copiavam.

    A ordem de efeitos e a do bloco substituido: `create_pending` (que gateia o
    acesso de ESCRITA e grava a trilha do F148 na mesma transacao) e so depois
    o envelope. O helper nao chama `ensure_account_access` por conta propria:
    quem gateia e o `create_pending`, como antes.

    `risk` e o retorno do `classify` da tool, e daqui sai so o `.reason` (como
    `confirmation_reason`). A DECISAO de emitir token — o `.level` (F112) —
    continua no source da tool: ou ela ramifica em `risk.level`, ou chama este
    helper incondicionalmente e o guard de `test_blast_radius_bate_com_as_tools`
    cobra que a politica concorde com esse caminho fixo.

    `operation` vira tambem o `operation_type` da pendencia: nas 20 tools os
    dois eram o mesmo literal.
    """
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type=operation,
            payload=payload,
            blast_summary=summary,
        )
    return preview_envelope(
        operation,
        customer_id,
        summary,
        token,
        confirmation_reason=risk.reason,
        **extra,
    )


def no_changes_envelope(operation: str, customer_id: str, **extra: Any) -> dict[str, Any]:
    """Envelope do no-op sem token (status=no_changes): nada a gravar, nada emitido.

    So o nucleo e fixo. Os dois no-op vivos divergem no corpo e cada um e
    contrato publicado da sua tool: `update_ad_schedule` devolve
    `no_changes/message/current_schedule`; `add_negative_keywords` devolve
    `applied_count: 0` e o relato da cobertura. Por isso nao ha `motivo`
    canonico aqui — impor uma chave de texto mudaria o shape das duas.
    """
    result: dict[str, Any] = {
        "status": "no_changes",
        "operation": operation,
        "customer_id": customer_id,
    }
    result.update(extra)
    return result
