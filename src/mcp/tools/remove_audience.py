# bucket: defer
"""Tool: remove_audience - detach audience criteria (user_list or user_interest)
previamente anexadas a 1 ad_group ou campaign.

Sprint 3b.6 (closes audience CRUD: 3b.4 create + 3b.5 validation + 3b.6 delete).

Always CONFIRM (spec §7.1 "Remove qualquer coisa = sempre confirma") — friction
trivial vs valor de prevenir accidental delivery restoration (exclusion removal
restaura audience à pool de delivery).

Visibilidade por linha (R1-I5, 2026-09-07): quem responde ao gestor e o
`apply_change`, e ele e GENERICO — nao conhece o vocabulario de dominio de tool
nenhuma. A tool manda `__partial_failure__=True` no payload, e o que volta e a
lista `partial_failures` com `{index, status, error}`: o `status` ali e
`success`/`failed` (o rotulo neutro do F152), e o motivo e a mensagem crua do
Google.

Ate 2026-09-07 este modulo tinha um `_classify_partial` que traduzia
RESOURCE_NOT_FOUND para `already_removed`, e a description anunciava esse
status per-row. **Ninguem chamava a funcao**, e nenhum caminho produzia o
status: a promessa era falsa nas duas pontas. Removidos os dois. Criterio ja
removido continua sendo idempotente na pratica (o lote nao cai por causa dele),
mas aparece como `failed` com a mensagem NOT_FOUND do Google — que e o que de
fato acontece.
"""

from typing import Any

from src.db import connection
from src.governance.blast_radius import classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._mutate_common import preview_envelope
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "target_type": {"type": "string", "enum": ["ad_group", "campaign"]},
        "target_id": {"type": "string", "pattern": "^[0-9]+$"},
        "criterion_ids": {
            "type": "array",
            "items": {"type": "string", "pattern": "^[0-9]+$"},
            "minItems": 1,
            "maxItems": 100,
        },
    },
    "required": ["customer_id", "target_type", "target_id", "criterion_ids"],
    "additionalProperties": False,
}


def _build_params_summary(target_type: str, target_id: str, criterion_count: int) -> dict[str, Any]:
    """Audit-safe summary: aggregate counts only.

    target_id included (numeric IDs carry no competitive signal). criterion_ids
    list NOT included (deterministic from existing audience attachments, no signal
    beyond count).
    """
    return {
        "target_type": target_type,
        "target_id": target_id,
        "criterion_count": criterion_count,
    }


@register_tool(
    name="remove_audience",
    description=(
        "[DEFER] Remove audience criteria (user_list ou user_interest) previamente anexadas "
        "a 1 ad_group ou campaign. Aceita target_type (ad_group|campaign) + "
        "target_id singular + criterion_ids array com ate 100 criteria do mesmo "
        "target. Sempre CONFIRM (spec §7.1 remove). Roda em partial_failure mode: "
        "criterion que o Google recusar (ja removido, id inexistente) NAO derruba o "
        "lote, e o apply_change devolve `partial_failures` com {index, status, error} "
        "por linha, `applied_count` e `failed_count`. Nao existe status "
        "por-linha de dominio: criterion ja removido volta como `failed` com a "
        "mensagem NOT_FOUND do Google. Pega criterion_id da response de "
        "get_audience_performance ou Google Ads UI."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def remove_audience(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    target_type = args["target_type"]
    target_id = args["target_id"]
    criterion_ids = args["criterion_ids"]
    target_count = len(criterion_ids)

    # Sem pre-flight (criterion_ids sao strings de digitos): o partial_failure mode
    # cuida de id inexistente sem derrubar o resto do lote, e o motivo por linha
    # sai em `partial_failures` na resposta do apply_change.

    risk = classify(operation="remove_audience", params={"target_count": target_count})
    # Always CONFIRM path — no AUTO branch

    payload = {
        "target_type": target_type,
        "target_id": target_id,
        "criterion_ids": criterion_ids,
        "__target_count__": target_count,
        "__partial_failure__": True,
        "__params_summary__": _build_params_summary(target_type, target_id, target_count),
    }
    summary = f"Remover {target_count} audience criteria do {target_type} {target_id}."

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="remove_audience",
            payload=payload,
            blast_summary=summary,
        )
    return preview_envelope(
        "remove_audience",
        customer_id,
        summary,
        token,
        confirmation_reason=risk.reason,
        target_type=target_type,
        target_id=target_id,
    )
