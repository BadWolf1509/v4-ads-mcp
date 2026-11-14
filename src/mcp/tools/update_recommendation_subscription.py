# bucket: defer
"""Tool: update_recommendation_subscription — pausa ou reativa a aplicacao automatica.

**Por que existe (N3, F185).** Na MO-JP a assinatura `RESPONSIVE_SEARCH_AD` esta
ENABLED desde 06/06/2024 e a tela de aplicacao automatica da UI nao lista esse tipo:
so a API a desliga. Pausa e reativa pelo mesmo mecanismo (reversivel), e nada alem
disso — criar assinatura seria ligar um auto-apply que nao existia.

Dry-run le o estado atual por GAQL e recusa: tipo sem assinatura na conta, tipo
`UNKNOWN`/ambiguo (F185: quatro linhas com o mesmo `resource_name` degenerado).
Ja no status pedido -> `no_changes`, sem token. Fora isso, sempre token (CONFIRM
fixo); o `apply_change` rele o status depois da escrita.
"""

from typing import Any

from src.google_ads.queries.recommendation_subscription import (
    STATUS_ALVO,
    TIPOS_ASSINAVEIS,
    assinatura_query,
    parse_assinatura_row,
)
from src.google_ads.reports import run_report
from src.governance.blast_radius import classify
from src.mcp.context import get_current
from src.mcp.tools._mutate_common import emitir_preview, error_envelope, no_changes_envelope
from src.mcp.tools._registry import register_tool

_OPERACAO = "update_recommendation_subscription"

_AVISO_ENABLED = (
    "ATENCAO: o Google passa a aplicar recomendacoes deste tipo sozinho, sem token "
    "nem preview deste MCP. Para desfazer, chame esta tool de novo com status PAUSED."
)

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "type": {
            "type": "string",
            "enum": list(TIPOS_ASSINAVEIS),
            "description": (
                "Tipo de recomendacao da assinatura (enum RecommendationType do Google "
                "Ads v25, sem UNKNOWN/UNSPECIFIED). Ex.: RESPONSIVE_SEARCH_AD. Para ver "
                "as assinaturas da conta: run_gaql com 'SELECT "
                "recommendation_subscription.type, recommendation_subscription.status "
                "FROM recommendation_subscription'."
            ),
        },
        "status": {"type": "string", "enum": list(STATUS_ALVO)},
    },
    "required": ["customer_id", "type", "status"],
    "additionalProperties": False,
}


@register_tool(
    name=_OPERACAO,
    description=(
        "[DEFER] Pausa (PAUSED) ou reativa (ENABLED) a aplicacao automatica de "
        "recomendacoes do Google Ads para UM tipo de recomendacao (assinatura). Util "
        "quando a UI nao lista o tipo (ex.: RESPONSIVE_SEARCH_AD, F185). So altera "
        "assinatura que ja existe: tipo sem assinatura e recusado (criar esta fora do "
        "escopo), e tipo UNKNOWN tambem (o Google devolve nome degenerado, F185). Se a "
        "assinatura ja esta no status pedido, responde no_changes sem token. Senao, "
        "SEMPRE devolve preview (antes -> depois) com confirmation_token; ENABLED vem "
        "com aviso de que o Google passa a aplicar sozinho. Aplicar via apply_change, "
        "que rele o status e devolve status_resultante; o veredito vai em "
        "`conferencia` na linha (divergente quando a releitura nao bate com o pedido), "
        "e `efeito` segue sendo o ACK do Google."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def update_recommendation_subscription(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    tipo = args["type"]
    status = args["status"]

    # Segunda barreira: o schema ja recusa, mas a tool nao depende so dele.
    if tipo not in TIPOS_ASSINAVEIS:
        return error_envelope(
            _OPERACAO,
            f"Tipo {tipo!r} nao e enderecavel: UNKNOWN/UNSPECIFIED vem do Google com "
            "resource_name degenerado e compartilhado entre assinaturas distintas "
            "(F185), entao nao ha como alterar so a assinatura certa. Nada foi feito.",
            customer_id=customer_id,
        )
    if status not in STATUS_ALVO:
        return error_envelope(
            _OPERACAO,
            f"status {status!r} fora do contrato (aceitos: {', '.join(STATUS_ALVO)}).",
            customer_id=customer_id,
        )

    linhas = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=assinatura_query(tipo),
        row_formatter=parse_assinatura_row,
        operation_name=f"{_OPERACAO}_lookup",
    )
    if not linhas:
        return error_envelope(
            _OPERACAO,
            f"A conta {customer_id} nao tem assinatura de aplicacao automatica para "
            f"{tipo}: criar assinatura esta fora do escopo desta tool (seria ligar um "
            "auto-apply que nao existia). Nada foi feito.",
            customer_id=customer_id,
        )
    if len(linhas) > 1:
        return error_envelope(
            _OPERACAO,
            f"A leitura devolveu {len(linhas)} assinaturas para o tipo {tipo}, que e a "
            "chave da assinatura — a resposta do Google esta ambigua (mesma familia do "
            "F185, resource_name repetido). Nada foi feito; confira no run_gaql.",
            customer_id=customer_id,
        )
    atual = linhas[0]
    status_antes = atual["status"]

    if status_antes == status:
        return no_changes_envelope(
            _OPERACAO,
            customer_id,
            message=f"A assinatura {tipo} ja esta {status}. Nenhum token emitido.",
            type=tipo,
            status_atual=status_antes,
            modify_date_time=atual["modify_date_time"],
        )

    risk = classify(
        operation="update_recommendation_subscription",
        params={"target_count": 1, "status": status},
    )
    aviso = _AVISO_ENABLED if status == "ENABLED" else None
    resumo = (
        f"Assinatura de aplicacao automatica {tipo} na conta {customer_id}: "
        f"{status_antes} -> {status}."
    )
    if aviso is not None:
        # O `apply_change` reexibe o `blast_summary`: aviso fora dele some na hora de
        # confirmar.
        resumo += f" {aviso}"
    payload = {
        "type": tipo,
        "status": status,
        "status_antes": status_antes,
        "__target_count__": 1,
        # Uma operacao so, mas com o relatorio por linha: e nele que vivem o `efeito`
        # (ACK do Google) e a `conferencia` que o pos-check preenche com a releitura.
        "__partial_failure__": True,
        # Audit: so tipo e status, nada de texto livre.
        "__params_summary__": {"type": tipo, "status": status},
    }
    return await emitir_preview(
        ctx,
        operation=_OPERACAO,
        customer_id=customer_id,
        payload=payload,
        resumo=resumo,
        risk=risk,
        type=tipo,
        status_antes=status_antes,
        status_depois=status,
        modify_date_time=atual["modify_date_time"],
        aviso=aviso,
    )
