# bucket: defer
"""Tool: meta_get_pages - paginas (e Instagram vinculado) que uma conta Meta Ads pode promover."""

from typing import Any

from src.mcp.context import get_current
from src.mcp.tools._meta_common import PROPRIEDADE_AD_ACCOUNT_ID, meta_erro
from src.mcp.tools._registry import register_tool
from src.meta_ads.client import MetaAccessDeniedError
from src.meta_ads.errors import MetaAdsFriendlyError
from src.meta_ads.paginas import listar_paginas

_OPERACAO = "meta_get_pages"
_LIMIT_PADRAO = 100
_LIMIT_MAX = 500

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ad_account_id": dict(PROPRIEDADE_AD_ACCOUNT_ID),
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": _LIMIT_MAX,
            "default": _LIMIT_PADRAO,
            "description": f"Máximo de páginas devolvidas (padrão {_LIMIT_PADRAO}, máximo {_LIMIT_MAX}).",
        },
    },
    "required": ["ad_account_id"],
    "additionalProperties": False,
}

_DESCRIPTION = (
    "[DEFER] Páginas do Facebook que UMA conta Meta Ads pode promover (uma conta por chamada), "
    "com o Instagram vinculado. Cada página traz `page_id`, `nome`, `instagram_id` e "
    "`instagram_origem` (`instagram_business_account` ou `connected_instagram_account`, o campo "
    "da Meta de onde o ID veio). Página sem Instagram traz `instagram_id: null` e "
    "`instagram_origem: null`. Conta sem páginas devolve lista vazia com sucesso. "
    "`truncated: true` = existem mais páginas que o `limit`. Somente leitura."
)


@register_tool(
    name=_OPERACAO,
    description=_DESCRIPTION,
    input_schema=_SCHEMA,
    bucket="defer",
)
async def meta_get_pages(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    ad_account_id = args["ad_account_id"]
    limit = int(args.get("limit", _LIMIT_PADRAO))
    if not 1 <= limit <= _LIMIT_MAX:
        return {
            "status": "error",
            "error_message": f"`limit` deve estar entre 1 e {_LIMIT_MAX} (recebido {limit}).",
        }
    try:
        paginas, truncated = await listar_paginas(ctx, ad_account_id, limit)
    except (MetaAccessDeniedError, MetaAdsFriendlyError) as e:
        return meta_erro(e)
    resposta: dict[str, Any] = {
        "status": "success",
        "ad_account_id": ad_account_id,
        "pages": paginas,
        "total_returned": len(paginas),
        "truncated": truncated,
    }
    if truncated:
        resposta["truncated_hint"] = (
            f"Há mais páginas que o limite de {limit}. Aumente `limit` (máximo {_LIMIT_MAX})."
        )
    return resposta
