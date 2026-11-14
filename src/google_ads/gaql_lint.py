"""Lint estatico do GAQL (spec 2026-11-14, N1) — sem chamada a API.

Compartilhado por `validate_gaql` e `run_gaql`. Analisa SO a lista entre SELECT e FROM: o mesmo
texto em literal do WHERE nao dispara. Nao altera `valid` nem `rows`: so acrescenta `avisos`.
"""

from src.google_ads.gaql_compacto import campos_do_select

AVISO_N1 = (
    "segments.date no SELECT: o Google so devolve linhas de (entidade, dia) com dado — "
    "entidade sem trafego no periodo NAO aparece. Para inventario, tire segments.date do "
    "SELECT; no WHERE ele nao esconde nada (medido em 14/11)."
)


def avisos_gaql(query: str) -> list[str]:
    """Avisos estaticos da query. Lista vazia quando nao ha nada a dizer (ou o SELECT nao le)."""
    campos = campos_do_select(query) or set()
    avisos: list[str] = []
    # N1: medido so para segments.date (week/month/etc. nao foram medidos).
    if "segments.date" in campos:
        avisos.append(AVISO_N1)
    return avisos
