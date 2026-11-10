# bucket: defer
"""Tool: meta_search_targeting - busca de interesses e segmentacoes de uma conta Meta Ads."""

from typing import Any

from src.mcp.context import get_current
from src.mcp.tools._meta_common import PROPRIEDADE_AD_ACCOUNT_ID, erro_de_entrada, meta_erro
from src.mcp.tools._registry import register_tool
from src.meta_ads.client import MetaAccessDeniedError
from src.meta_ads.errors import MetaAdsFriendlyError
from src.meta_ads.segmentacao import MOTIVO_TRUNCATED_DESCONHECIDO, buscar_segmentacao

_OPERACAO = "meta_search_targeting"
_LIMIT_PADRAO = 25
_LIMIT_MAX = 100

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ad_account_id": dict(PROPRIEDADE_AD_ACCOUNT_ID),
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
    "`descricao`. `null` = a Meta não informou, não é zero. `truncated: true` = há "
    "evidência de corte (a Meta devolveu o `limit` ou mais, ou indicou próxima página); refine "
    "o texto ou aumente o limite (máximo 100). `truncated: null` = sem evidência de corte, mas "
    "a Meta não informa se existem mais resultados (`truncated_motivo`): o conjunto muda "
    "conforme o `limit`, então nunca há `false`. Somente leitura."
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
        return erro_de_entrada(
            "`q` precisa ter ao menos 2 caracteres (sem contar espaços nas pontas)."
        )
    if not 1 <= limit <= _LIMIT_MAX:
        return erro_de_entrada(f"`limit` deve estar entre 1 e {_LIMIT_MAX} (recebido {limit}).")
    try:
        resultados, truncated = await buscar_segmentacao(ctx, ad_account_id, q, limit)
    except (MetaAccessDeniedError, MetaAdsFriendlyError) as e:
        return meta_erro(e)
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
            f"A busca chegou ao limite de {limit}, então pode haver mais resultados. "
            f"Refine `q` ou aumente `limit` (máximo {_LIMIT_MAX})."
        )
    else:
        resposta["truncated_motivo"] = MOTIVO_TRUNCATED_DESCONHECIDO
    return resposta
