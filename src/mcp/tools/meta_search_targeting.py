# bucket: defer
"""Tool: meta_search_targeting - busca de interesses e segmentacoes de uma conta Meta Ads."""

from typing import Any

from src.mcp.context import get_current
from src.mcp.tools._meta_common import meta_error_message
from src.mcp.tools._registry import register_tool
from src.meta_ads.segmentacao import buscar_segmentacao

_OPERACAO = "meta_search_targeting"
_LIMIT_PADRAO = 25
_LIMIT_MAX = 100

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
        "q": {
            "type": "string",
            "minLength": 2,
            "description": "Texto da busca (ao menos 2 caracteres), por exemplo `futebol`.",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": _LIMIT_MAX,
            "default": _LIMIT_PADRAO,
            "description": f"Máximo de resultados (padrão {_LIMIT_PADRAO}, máximo {_LIMIT_MAX}).",
        },
    },
    "required": ["ad_account_id", "q"],
    "additionalProperties": False,
}

_DESCRIPTION = (
    "[DEFER] Busca interesses e segmentações de UMA conta Meta Ads por texto (uma conta por "
    "chamada). Cada resultado traz `id`, `nome`, `tipo`, `caminho` (hierarquia), "
    "`audiencia_minima` e `audiencia_maxima` (faixa de alcance, limites separados) e "
    "`descricao`. `null` = a Meta não informou, não é zero. `truncated: true` = existem "
    "mais resultados que o `limit`; refine o texto ou aumente o limite (máximo 100). "
    "Somente leitura."
)


@register_tool(
    name=_OPERACAO,
    description=_DESCRIPTION,
    input_schema=_SCHEMA,
    bucket="defer",
)
async def meta_search_targeting(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    ad_account_id = args["ad_account_id"]
    q = str(args.get("q") or "").strip()
    limit = int(args.get("limit", _LIMIT_PADRAO))
    if len(q) < 2:
        return {
            "status": "error",
            "error_message": "`q` precisa ter ao menos 2 caracteres (sem contar espaços nas pontas).",
        }
    if not 1 <= limit <= _LIMIT_MAX:
        return {
            "status": "error",
            "error_message": f"`limit` deve estar entre 1 e {_LIMIT_MAX} (recebido {limit}).",
        }
    try:
        resultados, truncated = await buscar_segmentacao(ctx, ad_account_id, q, limit)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "error_message": meta_error_message(e)}
    resposta: dict[str, Any] = {
        "status": "success",
        "ad_account_id": ad_account_id,
        "q": q,
        "results": resultados,
        "total_returned": len(resultados),
        "truncated": truncated,
    }
    if truncated:
        resposta["truncated_hint"] = (
            f"Há mais resultados que o limite de {limit}. Refine `q` ou aumente `limit` "
            f"(máximo {_LIMIT_MAX})."
        )
    return resposta
