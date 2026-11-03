# bucket: always
"""Tool: meta_get_entities - campanhas, conjuntos ou anuncios Meta com status e orcamento."""

from typing import Any

from src.mcp.context import get_current
from src.mcp.tools._meta_common import meta_erro
from src.mcp.tools._registry import register_tool
from src.meta_ads.client import MetaAccessDeniedError
from src.meta_ads.entidades import listar_entidades
from src.meta_ads.errors import MetaAdsFriendlyError
from src.meta_ads.reports import run_meta_graph_get

_OPERACAO = "meta_get_entities"

_STATUS = [
    "ACTIVE",
    "PAUSED",
    "ARCHIVED",
    "DELETED",
    "IN_PROCESS",
    "WITH_ISSUES",
    "CAMPAIGN_PAUSED",
    "ADSET_PAUSED",
    "PENDING_REVIEW",
    "DISAPPROVED",
    "PENDING_BILLING_INFO",
]

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ad_account_id": {
            "type": "string",
            "pattern": r"^act_\d+$",
            "description": (
                "Meta ad account ID (formato act_<numeric>). "
                "Use meta_list_my_ad_accounts pra descobrir IDs disponíveis."
            ),
        },
        "level": {
            "type": "string",
            "enum": ["campaign", "adset", "ad"],
            "description": "campaign = campanhas, adset = conjuntos de anúncios, ad = anúncios.",
        },
        "status": {
            "type": "string",
            "enum": _STATUS,
            "description": (
                "Filtra pelo status EFETIVO (`effective_status`). Omitido, vale o padrão da "
                "Meta, que pode deixar de fora itens arquivados ou apagados."
            ),
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 500,
            "default": 100,
            "description": "Máximo de entidades devolvidas (padrão 100, máximo 500).",
        },
    },
    "required": ["ad_account_id", "level"],
    "additionalProperties": False,
}

_DESCRIPTION = (
    "[CORE] Lista campanhas, conjuntos ou anúncios de UMA conta Meta Ads (uma conta por chamada), "
    "com status e orçamento, que as tools de desempenho não mostram. `status` é o status "
    "configurado e `effective_status` o efetivo: um conjunto ou anúncio "
    "ACTIVE pode estar parado porque o pai está pausado (ex.: CAMPAIGN_PAUSED, ADSET_PAUSED); "
    "a campanha não tem pai, mas seu efetivo também pode diferir do configurado; leia os dois. "
    "Orçamentos em BRL: `daily_budget_brl`, `lifetime_budget_brl` e `budget_remaining_brl`; "
    "`null` = a Meta não reportou ou a entidade não tem orçamento próprio (nunca zero). "
    "Em conjunto, `orcamento_em` diz onde está o orçamento: 'conjunto' quando ele tem o "
    "seu, 'campanha' quando não tem e vale o da campanha. `issues_info`, "
    "`learning_stage_info` e `ad_review_feedback` vêm como a Meta devolve, `null` quando "
    "ausentes. O filtro `status` age sobre o status efetivo. `truncated: true` = existem "
    "mais entidades que o `limit`; aumente o limite ou filtre por status. Conta vazia "
    "devolve `entities: []`. Só contas em BRL. Somente leitura."
)


@register_tool(
    name=_OPERACAO,
    description=_DESCRIPTION,
    input_schema=_SCHEMA,
    bucket="always",
)
async def meta_get_entities(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    ad_account_id = args["ad_account_id"]
    level = args["level"]
    status = args.get("status")
    limit = int(args.get("limit", 100))
    if not 1 <= limit <= 500:
        return {
            "status": "error",
            "error_message": f"`limit` deve estar entre 1 e 500 (recebido {limit}).",
        }
    try:
        conta = await run_meta_graph_get(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            ad_account_id=ad_account_id,
            edge=f"/{ad_account_id}",
            params={"fields": "currency"},
            operation_name=_OPERACAO,
            estimated_calls=1,
            audit_this_call=True,
            params_summary={"ad_account_id": ad_account_id, "call": "moeda"},
        )
        moeda = conta.get("currency")
        if moeda != "BRL":
            return {
                "status": "error",
                "error_message": (
                    f"conta Meta em moeda {moeda!r}: as entidades só são lidas para contas em BRL"
                ),
            }
        entidades, truncated = await listar_entidades(ctx, ad_account_id, level, status, limit)
    except (MetaAccessDeniedError, MetaAdsFriendlyError) as e:
        return meta_erro(e)
    resposta: dict[str, Any] = {
        "status": "success",
        "ad_account_id": ad_account_id,
        "level": level,
        "entities": entidades,
        "total_returned": len(entidades),
        "truncated": truncated,
    }
    if truncated:
        resposta["truncated_hint"] = (
            f"Há mais entidades que o limite de {limit}. Aumente `limit` (máximo 500) "
            "ou filtre por `status`."
        )
    return resposta
