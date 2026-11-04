"""Helpers compartilhados pelas tools Meta MCP."""

from typing import Any

from src.meta_ads.client import MetaAccessDeniedError
from src.meta_ads.errors import MetaAdsFriendlyError


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
        return {"status": "error", "error_message": exc.message}
    raise exc
