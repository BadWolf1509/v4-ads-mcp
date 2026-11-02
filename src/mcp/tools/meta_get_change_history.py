# bucket: defer
"""Tool: meta_get_change_history - quem mudou o que numa conta Meta Ads."""

from datetime import timedelta
from typing import Any

from src.mcp.context import get_current
from src.mcp.tools._meta_common import meta_error_message
from src.mcp.tools._registry import register_tool
from src.meta_ads.account_clock import resolve_meta_account_today
from src.meta_ads.historico import listar_atividades

_OPERACAO = "meta_get_change_history"
_DIAS_PADRAO = 7
_DIAS_MAX = 30

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
        "days": {
            "type": "integer",
            "minimum": 1,
            "maximum": _DIAS_MAX,
            "default": _DIAS_PADRAO,
            "description": (
                "Quantos dias olhar para trás, contando hoje (padrão 7, máximo 30), "
                "no fuso da conta."
            ),
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 500,
            "default": 100,
            "description": "Máximo de alterações devolvidas (padrão 100, máximo 500).",
        },
    },
    "required": ["ad_account_id"],
    "additionalProperties": False,
}

_DESCRIPTION = (
    "[DEFER] Histórico de alterações de UMA conta Meta Ads (uma conta por chamada): quem "
    "mudou o quê e quando. Cada registro traz `ocorrido_em` (UTC), `ocorrido_em_fuso_conta` (texto no fuso da conta, como a Meta devolve), `ator_id`, `ator_nome`, `tipo` "
    "(event_type da Meta), `objeto_id`, `objeto_nome`, `objeto_tipo` (campanha, conjunto, anuncio, conta; "
    "tipo desconhecido passa como a Meta devolve) e `detalhe` (o `extra_data` decodificado; "
    "texto quando não for JSON). `null` = a Meta não informou (por exemplo, alteração feita "
    "pelo sistema sem ator). A janela é fechada e termina hoje no fuso da conta: padrão 7 "
    "dias, máximo 30; a resposta declara a janela efetiva em `date_range` e só devolve evento "
    "cuja data no fuso da conta está nela. Evento com data ilegível não é descartado: vem com "
    "`data_nao_verificada: true`, fora da garantia da janela. Sem o fuso da conta a tool "
    "devolve erro. `truncated: true` = há ou pode haver mais alterações na janela além das "
    "devolvidas; aumente o limite ou reduza `days`. Somente leitura."
)


@register_tool(
    name=_OPERACAO,
    description=_DESCRIPTION,
    input_schema=_SCHEMA,
    bucket="defer",
)
async def meta_get_change_history(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    ad_account_id = args["ad_account_id"]
    dias = int(args.get("days", _DIAS_PADRAO))
    limit = int(args.get("limit", 100))
    if not 1 <= dias <= _DIAS_MAX:
        return {
            "status": "error",
            "error_message": f"`days` deve estar entre 1 e {_DIAS_MAX} (recebido {dias}).",
        }
    try:
        fim = await resolve_meta_account_today(ad_account_id)
        inicio = fim - timedelta(days=dias - 1)
        registros, truncated = await listar_atividades(ctx, ad_account_id, inicio, fim, limit)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "error_message": meta_error_message(e)}
    resposta: dict[str, Any] = {
        "status": "success",
        "ad_account_id": ad_account_id,
        "date_range": {"start": inicio.isoformat(), "end": fim.isoformat(), "days": dias},
        "changes": registros,
        "total_returned": len(registros),
        "truncated": truncated,
    }
    if truncated:
        resposta["truncated_hint"] = (
            f"Pode haver mais alterações na janela além das {len(registros)} devolvidas "
            f"(limite {limit}). Aumente `limit` (máximo 500) ou reduza `days`."
        )
    return resposta
