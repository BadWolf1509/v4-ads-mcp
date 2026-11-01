# bucket: defer
"""Tool: meta_get_delivery_estimate - estimativa de entrega para uma segmentacao."""

import contextlib
import json
from typing import Any

from src.mcp.context import get_current
from src.mcp.tools._meta_common import meta_error_message
from src.mcp.tools._registry import register_tool
from src.meta_ads.segmentacao import estimar_entrega

_OPERACAO = "meta_get_delivery_estimate"
_OBJETIVOS = [
    "REACH",
    "LINK_CLICKS",
    "LANDING_PAGE_VIEWS",
    "LEAD_GENERATION",
    "CONVERSATIONS",
    "OFFSITE_CONVERSIONS",
    "IMPRESSIONS",
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
        "targeting_spec": {
            "type": "object",
            "description": (
                "Segmentação como objeto JSON no formato da Meta, por exemplo "
                '{"geo_locations": {"countries": ["BR"]}, "age_min": 25}. '
                "Use meta_search_targeting para achar IDs de interesses."
            ),
        },
        "optimization_goal": {
            "type": "string",
            "enum": _OBJETIVOS,
            "default": "REACH",
            "description": (
                "Objetivo de otimização da estimativa (padrão REACH). Somente REACH foi "
                "medido contra a API; os demais podem ser recusados pela Meta."
            ),
        },
    },
    "required": ["ad_account_id", "targeting_spec"],
    "additionalProperties": False,
}

_DESCRIPTION = (
    "[DEFER] Estimativa de entrega de UMA conta Meta Ads para uma segmentação (uma conta por "
    "chamada). Devolve em `estimate`: `alcance_mensal_minimo`, `alcance_mensal_maximo`, "
    "`alcance_diario` e `estimativa_pronta`. A estimativa é sempre aproximada "
    "(`aproximado: true`): a Meta devolve faixas, não valores exatos. `null` = a Meta não "
    "informou, não é zero. `estimativa_pronta: false` = a Meta ainda não terminou de "
    "calcular; os valores vêm como a Meta devolveu. Sem dados, `estimate` é `null` com o "
    "motivo em `reason`. Somente leitura."
)


@register_tool(
    name=_OPERACAO,
    description=_DESCRIPTION,
    input_schema=_SCHEMA,
    bucket="defer",
)
async def meta_get_delivery_estimate(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    ad_account_id = args["ad_account_id"]
    spec = args.get("targeting_spec")
    objetivo = args.get("optimization_goal") or "REACH"
    if isinstance(spec, str):  # o cliente pode serializar o objeto como texto (F1)
        with contextlib.suppress(ValueError):
            spec = json.loads(spec)
    if not isinstance(spec, dict):
        return {
            "status": "error",
            "error_message": (
                "`targeting_spec` precisa ser um objeto JSON (por exemplo "
                '{"geo_locations": {"countries": ["BR"]}}), não texto, lista ou número.'
            ),
        }
    if objetivo not in _OBJETIVOS:
        return {
            "status": "error",
            "error_message": (
                f"`optimization_goal` inválido ({objetivo!r}). Valores: {', '.join(_OBJETIVOS)}."
            ),
        }
    try:
        estimativa = await estimar_entrega(ctx, ad_account_id, spec, objetivo)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "error_message": meta_error_message(e)}
    resposta: dict[str, Any] = {
        "status": "success",
        "ad_account_id": ad_account_id,
        "optimization_goal": objetivo,
        "aproximado": True,
        "estimate": estimativa,
    }
    if estimativa is None:
        resposta["reason"] = (
            "A Meta não devolveu estimativa para esta segmentação e objetivo. "
            "Isso não significa alcance zero."
        )
    return resposta
