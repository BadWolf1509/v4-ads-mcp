# bucket: defer
"""Tool: meta_get_creatives - criativos de uma conta Meta Ads."""

from typing import Any

from src.mcp.context import get_current
from src.mcp.tools._meta_common import meta_error_message
from src.mcp.tools._registry import register_tool
from src.meta_ads.criativos import PosseNaoProvada, listar_criativos

_OPERACAO = "meta_get_creatives"

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
        "ad_id": {
            "type": "string",
            "pattern": r"^\d+$",
            "description": (
                "Opcional. ID de um anúncio DESTA conta: devolve só o criativo dele, com "
                "`ads_vinculados` (os anúncios da conta que usam o mesmo criativo)."
            ),
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 500,
            "default": 100,
            "description": "Máximo de criativos devolvidos (padrão 100, máximo 500).",
        },
    },
    "required": ["ad_account_id"],
    "additionalProperties": False,
}

_DESCRIPTION = (
    "[DEFER] Criativos de UMA conta Meta Ads (uma conta por chamada): `id`, `name`, `status`, "
    "`object_type`, `title`, `body`, `image_url`, `thumbnail_url`, `call_to_action_type`, "
    "`object_story_id`, `effective_object_story_id`, `instagram_permalink_url`. `null` = a "
    "Meta não informou (criativo sem imagem ou sem texto traz esses campos nulos). Com "
    "`ad_id` (anúncio da conta), devolve só o criativo daquele anúncio e `ads_vinculados` "
    "lista os anúncios da conta que o usam (sem `ad_id`, `ads_vinculados` é `null`). A "
    "busca do `ad_id` olha até 1000 anúncios; se não achar, devolve erro (pode ser conta "
    "grande). `truncated: true` = existem mais criativos que o `limit`. Somente leitura."
)


@register_tool(
    name=_OPERACAO,
    description=_DESCRIPTION,
    input_schema=_SCHEMA,
    bucket="defer",
)
async def meta_get_creatives(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    ad_account_id = args["ad_account_id"]
    ad_id = args.get("ad_id")
    limit = int(args.get("limit", 100))
    if ad_id is not None and not (isinstance(ad_id, str) and ad_id.isascii() and ad_id.isdigit()):
        return {"status": "error", "error_message": "`ad_id` deve ser numérico."}
    if not 1 <= limit <= 500:
        return {
            "status": "error",
            "error_message": f"`limit` deve estar entre 1 e 500 (recebido {limit}).",
        }
    try:
        criativos, truncated = await listar_criativos(ctx, ad_account_id, limit, ad_id, _OPERACAO)
    except PosseNaoProvada as e:
        return {"status": "error", "error_message": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "error_message": meta_error_message(e)}
    resposta: dict[str, Any] = {
        "status": "success",
        "ad_account_id": ad_account_id,
        "creatives": criativos,
        "total_returned": len(criativos),
        "truncated": truncated,
    }
    if truncated:
        resposta["truncated_hint"] = (
            f"Há mais criativos que o limite de {limit}. Aumente `limit` (máximo 500)."
        )
    return resposta
