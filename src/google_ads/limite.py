"""Corte de linhas por `limit` (idioma `fetch n+1`), neutro entre dominio e tools MCP."""


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
