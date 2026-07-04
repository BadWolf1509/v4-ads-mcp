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

from src.governance.dry_run import DEFAULT_TTL_MINUTES

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
    auto_applied_reason: str,
    **extra: Any,
) -> dict[str, Any]:
    """Envelope canônico de sucesso AUTO-apply (status=applied).

    `**extra` carrega campos por-tool (changes[], added[], attachments_result[],
    resource_names, etc).
    """
    result: dict[str, Any] = {
        "status": "applied",
        "operation": operation,
        "customer_id": customer_id,
        "blast_summary": blast_summary,
        "applied_count": applied_count,
        "provider_request_id": provider_request_id,
        "auto_applied_reason": auto_applied_reason,
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
