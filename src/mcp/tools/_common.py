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
