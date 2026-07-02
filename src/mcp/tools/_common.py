"""Helpers compartilhados pelas tools MCP (partial-failure classification etc.)."""


def classify_partial(
    error: str | None,
    *,
    ok_status: str,
    exists_status: str,
    exists_patterns: tuple[str, ...],
) -> str:
    """Mapeia o erro de partial-failure de UMA linha pro status por-linha.

    - error=None            → ok_status (a linha aplicou).
    - casa um exists_pattern → exists_status (idempotência: já existe / já anexado).
    - senão                 → "failed".

    Centraliza o _classify_partial que estava copiado idêntico em add_keywords /
    add_negatives_from_search_terms / apply_audience (só mudavam os 3 rótulos).
    """
    if error is None:
        return ok_status
    upper = error.upper()
    if any(p in upper for p in exists_patterns):
        return exists_status
    return "failed"
