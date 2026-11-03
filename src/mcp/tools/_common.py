"""Helpers compartilhados pelas tools MCP (partial-failure classification etc.)."""

import copy
from collections.abc import Sequence
from datetime import date
from typing import Any

from src.google_ads.account_clock import resolve_account_today
from src.google_ads.limite import aplicar_limite as aplicar_limite  # reexport
from src.google_ads.queries._common import resolve_date_window
from src.janelas import PRESETS_EM_ORDEM

_PADRAO_DE_DATA = "^\\d{4}-\\d{2}-\\d{2}$"

_START_E_END: dict[str, Any] = {
    "start_date": {
        "type": "string",
        "pattern": _PADRAO_DE_DATA,
        "description": (
            "Data inicial YYYY-MM-DD inclusive. Quando informado junto com end_date, "
            "sobrepoe date_range preset. Obriga end_date."
        ),
    },
    "end_date": {
        "type": "string",
        "pattern": _PADRAO_DE_DATA,
        "description": "Data final YYYY-MM-DD inclusive. Obrigatorio se start_date informado.",
    },
}


def propriedades_de_data(
    default: str = "LAST_30_DAYS", presets: Sequence[str] = PRESETS_EM_ORDEM
) -> dict[str, Any]:
    """O trio `date_range` + `start_date` + `end_date` do schema de uma tool Google.

    Preset com `type: "string"` + `enum` e o par custom com `type` explicito (F1: sem
    `type`, o Claude serializava o dict como string). Serve so as tools cujo trio JA e
    este, literal: tool com enum, default ou description proprios fica com o dela, porque
    o schema e contrato do handshake (`test_schemas_snapshot.py`). Devolve copia nova a
    cada chamada — um schema nao pode mexer no do vizinho.
    """
    enum = list(presets)
    if default not in enum:
        raise ValueError(f"default {default!r} fora dos presets do schema: {enum}")
    return {
        "date_range": {
            "type": "string",
            "enum": enum,
            "default": default,
            "description": "Periodo via preset. Para periodo custom, use start_date+end_date.",
        },
        **copy.deepcopy(_START_E_END),
    }


async def janela_da_conta(
    ctx: Any,
    args: dict[str, Any],
    customer_id: str,
    *,
    default: str = "LAST_30_DAYS",
) -> tuple[date, date, date]:
    """(inicio, fim, hoje) da janela pedida, com `hoje` no fuso da CONTA (F141).

    `hoje` sai de `resolve_account_today`, uma vez por chamada, nunca do relogio do
    servidor (guard `test_no_server_clock_in_google_tools`). A ordem e a que as tools
    ja tinham: resolve `hoje` e so entao valida a janela, com as mensagens de
    `resolve_date_window` (`InvalidDateRangeError`, uma `EntradaInvalidaError`).
    Quem ja tem um `hoje` desta request (o corpo do `get_change_history`, chamado em
    serie pelo `detect_drift`) nao usa este helper: resolver de novo daria um segundo
    `hoje` no meio da varredura.

    `ctx` e o contexto da request, recebido para a assinatura ficar a mesma das
    tools que o chamam; a janela nao depende dele.
    """
    del ctx
    hoje = await resolve_account_today(customer_id)
    inicio, fim = resolve_date_window(
        date_range=args.get("date_range", default),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
        today=hoje,
    )
    return inicio, fim, hoje


def classify_partial(
    error: str | None,
    *,
    status: str,
    ok_status: str,
    exists_status: str,
    exists_patterns: tuple[str, ...],
) -> str:
    """Mapeia o veredito + erro de partial-failure de UMA linha pro status por-linha.

    `status` ("success" | "failed" — o WhichOneof/heuristica que MEDE se a
    linha aplicou) decide PRIMEIRO, nao `error`. Ate 21/09 `error is None`
    sozinho significava "aplicou" — certo enquanto `error` so podia ser None
    por ausencia de erro. Ficou errado quando `error` passou a poder ser
    `None` por um segundo motivo, incompativel com o primeiro: "houve erro
    mas o motivo nao foi lido" (leitura.medido=False em erros_por_indice,
    Task 2/4). Uma linha que o WhichOneof MEDIU como falha, com motivo nao
    lido, virava `ok_status` por aqui — o status mentia, na direcao mais
    perigosa (CRITICAL achado na revisao pos-Task 4, fix round 1/5).

    - status="success"                            -> ok_status (a linha aplicou;
      `error` e ignorado).
    - status="failed" e `error` casa um exists_pattern -> exists_status
      (idempotencia: ja existe / ja anexado).
    - status="failed", qualquer outro caso (inclusive error=None, motivo nao
      lido) -> "failed".

    Centraliza o _classify_partial que estava copiado idêntico em add_keywords /
    add_negatives_from_search_terms / apply_audience (só mudavam os 3 rótulos).
    """
    if status == "success":
        return ok_status
    if error is not None:
        upper = error.upper()
        if any(p in upper for p in exists_patterns):
            return exists_status
    return "failed"
