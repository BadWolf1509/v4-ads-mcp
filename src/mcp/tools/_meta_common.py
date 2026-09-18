"""Helpers compartilhados pelas tools Meta MCP (Sprint M.2a Task 9 onwards)."""

# Labels vivem em src.meta_ads.labels (domínio, não helper de tool). Re-exportadas
# aqui por herança de quando o painel (pré-split de src/web/routes.py) as
# consumia por este caminho. Desde o split (PR 5) o painel importa direto de
# src.meta_ads.labels (ver src/web/routes/_shared.py) — medido em 18/09: zero
# `from src.mcp.tools._meta_common import` cita META_ACCOUNT_STATUS_LABELS,
# nem no painel nem nas tools MCP (as 3 que importam deste módulo hoje usam só
# `meta_error_message`, abaixo). Re-export mantido por compatibilidade; se
# nenhum caller aparecer numa próxima varredura, remover é limpeza separada.
# Import novo? Prefira `from src.meta_ads.labels import ...`.
# F89: o re-export de META_EFFECTIVE_STATUS_LABELS saiu junto — seu unico
# consumidor era o parser de insights, que parou de devolver o campo.
from src.meta_ads.labels import (  # noqa: F401
    META_ACCOUNT_STATUS_LABELS as META_ACCOUNT_STATUS_LABELS,
)


def meta_error_message(exc: Exception) -> str:
    """Mensagem de um erro Meta pro envelope do tool.

    MetaAdsFriendlyError carrega `.message` (PT-BR curada); o resto cai no str(exc).
    Centraliza o padrão `if hasattr(e, "message")` que estava repetido nos 5 tools
    Meta. getattr+isinstance é mypy-clean e robusto a `.message` não-str.
    """
    message = getattr(exc, "message", None)
    return message if isinstance(message, str) else str(exc)
