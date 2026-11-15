# bucket: defer
"""Tool: update_campaign_status - pause/enable/remove campaigns."""

from typing import Any

from src.governance.blast_radius import classify
from src.mcp.context import get_current
from src.mcp.tools._mutate_common import aplicar_ou_pedir_confirmacao
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "campaign_ids": {
            "type": "array",
            "items": {"type": "string", "pattern": "^[0-9]+$"},
            "minItems": 1,
            # F183: campanha e a entidade de maior raio — cada item mexe em todos os
            # grupos e anuncios abaixo dela. Teto menor que o dos irmaos de propósito.
            "maxItems": 50,
        },
        "new_status": {
            "type": "string",
            "enum": ["ENABLED", "PAUSED"],
        },
    },
    "required": ["customer_id", "campaign_ids", "new_status"],
    "additionalProperties": False,
}


@register_tool(
    name="update_campaign_status",
    description=(
        "[DEFER] Pausa ou ativa uma ou mais campanhas. Ate 5 campanhas auto-aplica; "
        ">5 retorna preview com confirmation_token (chamar apply_change pra aplicar). "
        "Para REMOVER campanhas, use Google Ads UI (tool dedicada `remove_campaign` "
        "pode ser adicionada em sprint futura se demanda real surgir). "
        "Nota: campaign.status pode lagar alguns minutos entre queries Google Ads — "
        "se decisao critica (ex: pausar campanha REMOVED), re-query antes de agir."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def update_campaign_status(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    campaign_ids = args["campaign_ids"]
    new_status = args["new_status"]
    target_count = len(campaign_ids)

    risk = classify(
        operation="update_campaign_status",
        params={"target_count": target_count, "new_status": new_status},
    )
    payload = {
        "campaign_ids": campaign_ids,
        "new_status": new_status,
        "__target_count__": target_count,
    }
    summary = (
        f"Mudar status de {target_count} campanha(s) "
        f"({', '.join(campaign_ids[:3])}{'...' if target_count > 3 else ''}) "
        f"para {new_status}."
    )

    return await aplicar_ou_pedir_confirmacao(
        ctx,
        operation="update_campaign_status",
        customer_id=customer_id,
        payload=payload,
        target_count=target_count,
        resumo=summary,
        risk=risk,
    )
