# bucket: defer
"""Tool: meta_get_ad_preview - URL da previa de um criativo/anuncio Meta Ads."""

from typing import Any

from src.mcp.context import get_current
from src.mcp.tools._meta_common import meta_erro
from src.mcp.tools._registry import register_tool
from src.meta_ads.client import MetaAccessDeniedError
from src.meta_ads.criativos import (
    FORMATOS,
    PosseNaoProvada,
    extrair_src_iframe,
    gerar_previa,
    provar_posse,
)
from src.meta_ads.errors import MetaAdsFriendlyError

_OPERACAO = "meta_get_ad_preview"
_PADRAO = "MOBILE_FEED_STANDARD"

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
            "description": "ID de um anúncio da conta. Informe este OU `creative_id`, nunca os dois.",
        },
        "creative_id": {
            "type": "string",
            "pattern": r"^\d+$",
            "description": "ID de um criativo da conta. Informe este OU `ad_id`, nunca os dois.",
        },
        "ad_format": {
            "type": "string",
            "enum": FORMATOS,
            "default": _PADRAO,
            "description": f"Formato da prévia (padrão {_PADRAO}).",
        },
    },
    "required": ["ad_account_id"],
    "additionalProperties": False,
}

_DESCRIPTION = (
    "[DEFER] Prévia de um anúncio ou criativo de UMA conta Meta Ads (uma conta por chamada). "
    "Informe exatamente um de `ad_id` ou `creative_id`. Devolve `preview_url`, o endereço "
    "(facebook.com) da prévia para abrir no navegador, nunca o HTML. Antes de gerar, a "
    "tool prova que o ID pertence à conta (a Meta serviria o criativo de outra conta): "
    "olha até 1000 registros e, se não achar o ID, recusa com erro (pode ser conta "
    "grande). Somente leitura."
)


def _erro(msg: str) -> dict[str, Any]:
    return {"status": "error", "error_message": msg}


def _numerico(v: Any) -> bool:
    return isinstance(v, str) and v.isascii() and v.isdigit()


@register_tool(
    name=_OPERACAO,
    description=_DESCRIPTION,
    input_schema=_SCHEMA,
    bucket="defer",
)
async def meta_get_ad_preview(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    ad_account_id = args["ad_account_id"]
    ad_id = args.get("ad_id")
    creative_id = args.get("creative_id")
    ad_format = args.get("ad_format", _PADRAO)
    if (ad_id is None) == (creative_id is None):
        return _erro("informe exatamente um de `ad_id` ou `creative_id`.")
    if (ad_id is not None and not _numerico(ad_id)) or (
        creative_id is not None and not _numerico(creative_id)
    ):
        return _erro("`ad_id` e `creative_id` devem ser numéricos.")
    if ad_format not in FORMATOS:
        return _erro(f"`ad_format` inválido; use um de: {', '.join(FORMATOS)}.")
    try:
        cid = await provar_posse(
            ctx, ad_account_id, _OPERACAO, ad_id=ad_id, creative_id=creative_id
        )
        corpo = await gerar_previa(ctx, ad_account_id, cid, ad_format, _OPERACAO)
    except PosseNaoProvada as e:
        return _erro(str(e))
    except (MetaAccessDeniedError, MetaAdsFriendlyError) as e:
        return meta_erro(e)
    src = extrair_src_iframe(corpo)
    if src is None:
        return _erro(
            "a Meta não devolveu uma prévia utilizável (sem endereço facebook.com válido)."
        )
    return {
        "status": "success",
        "ad_account_id": ad_account_id,
        "creative_id": cid,
        "ad_format": ad_format,
        "preview_url": src,
    }
