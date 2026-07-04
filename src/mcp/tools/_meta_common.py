"""Helpers compartilhados pelas tools Meta MCP (Sprint M.2a Task 9 onwards)."""

# Labels vivem em src.meta_ads.labels (domínio, não helper de tool). Re-exportadas
# aqui pra manter os call-sites antigos funcionando sem quebra (web routes.py +
# src.meta_ads.insights). Import novo? Prefira `from src.meta_ads.labels import ...`.
from src.meta_ads.labels import (  # noqa: F401
    META_ACCOUNT_STATUS_LABELS as META_ACCOUNT_STATUS_LABELS,
)
from src.meta_ads.labels import (  # noqa: F401
    META_EFFECTIVE_STATUS_LABELS as META_EFFECTIVE_STATUS_LABELS,
)


def meta_error_message(exc: Exception) -> str:
    """Mensagem de um erro Meta pro envelope do tool.

    MetaAdsFriendlyError carrega `.message` (PT-BR curada); o resto cai no str(exc).
    Centraliza o padrão `if hasattr(e, "message")` que estava repetido nos 5 tools
    Meta. getattr+isinstance é mypy-clean e robusto a `.message` não-str.
    """
    message = getattr(exc, "message", None)
    return message if isinstance(message, str) else str(exc)
