"""Helpers compartilhados pelas tools Meta MCP."""

from typing import Any

from src.meta_ads.client import MetaAccessDeniedError
from src.meta_ads.errors import MetaAdsFriendlyError

# Propriedade `ad_account_id` do input schema, idêntica em 13 tools Meta. Cada tool
# usa `dict(PROPRIEDADE_AD_ACCOUNT_ID)` (cópia rasa) para ninguém mutar o compartilhado.
# `meta_get_performance_breakdown` tem description própria (contrato) e não a usa.
PROPRIEDADE_AD_ACCOUNT_ID: dict[str, Any] = {
    "type": "string",
    "pattern": r"^act_\d+$",
    "description": (
        "Meta ad account ID (formato act_<numeric>). "
        "Use meta_list_my_ad_accounts pra descobrir IDs disponíveis."
    ),
}


def erro_de_entrada(mensagem: str) -> dict[str, Any]:
    """Envelope de erro de duas chaves, `{"status": "error", "error_message": ...}`.

    Serve a qualquer erro não-`denied` de tool Meta que o cliente deve ler: erro
    de entrada, conta só em BRL, campo ausente, preview inutilizável. O nome é
    histórico (nasceu só para entrada); renomear tocaria 25 pontos sem ganho de contrato.
    """
    return {"status": "error", "error_message": mensagem}


def meta_erro(exc: Exception) -> dict[str, Any]:
    """Envelope de erro de uma tool Meta, só para os dois erros que ela PODE explicar.

    Negação de acesso vira `denied` (como o `_error_envelope` central trata) e
    `MetaAdsFriendlyError` (PT-BR curada) vira `error` com a sua `.message`.
    Qualquer outra exceção sobe: o `_error_envelope` esconde o `str(exc)` interno.
    As tools só chamam isto dentro de `except (MetaAccessDeniedError, MetaAdsFriendlyError)`.
    """
    if isinstance(exc, MetaAccessDeniedError):
        return {"status": "denied", "error_message": exc.message}
    if isinstance(exc, MetaAdsFriendlyError):
        return erro_de_entrada(exc.message)
    raise exc
