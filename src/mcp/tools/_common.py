"""Helpers compartilhados pelas tools MCP (partial-failure classification etc.)."""


def aplicar_limite[T](linhas: list[T], limite: int) -> tuple[list[T], bool]:
    """Devolve (linhas cortadas, truncated). Único lugar que decide o corte.

    **Contrato:** `linhas` tem que vir de uma consulta pedida com `limite + 1`.
    É a única forma de distinguir "vieram exatamente `limite`" de "havia mais".
    Pedir `LIMIT {limite}` e comparar `len(linhas) > limite` aqui devolve
    `False` SEMPRE, e o detector morre calado — que é o defeito que este
    primitivo existe para fechar, não uma sutileza de estilo.

    O `+1` já é o idioma do repo: `ad_schedule`, `overview` e `recommendations`
    o usam desde que ganharam `truncated`. As 9 tools desta frente usavam
    `LIMIT {limit}` — daí a mentira.
    """
    return linhas[:limite], len(linhas) > limite


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
