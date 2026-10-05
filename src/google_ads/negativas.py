"""Regras puras das negativas de keyword (spec 2026-10-05, §3.1).

O Google não aplica variante próxima em negativa (medido na MO-JP, 05/10): acento, plural e
erro de digitação são negativas distintas. Por isso a `chave` de comparação mantém o acento, e
`sem_acento` existe para SUGERIR o par, nunca para igualar os dois.

Cobertura só entre negativas de MESMO texto: BROAD cobre PHRASE e EXACT, PHRASE cobre EXACT.
Texto diferente não se compara — a semântica de negativa ampla de várias palavras entre textos
distintos não foi medida.
"""

import unicodedata
from typing import Any

AMPLITUDE: dict[str, int] = {"EXACT": 0, "PHRASE": 1, "BROAD": 2}


def sem_acento(texto: str) -> str | None:
    """O texto sem diacríticos, ou `None` quando não havia acento. Caixa e espaço intactos."""
    decomposto = unicodedata.normalize("NFD", texto)
    limpo = unicodedata.normalize(
        "NFC", "".join(c for c in decomposto if not unicodedata.combining(c))
    )
    return None if limpo == unicodedata.normalize("NFC", texto) else limpo


def chave(texto: str) -> str:
    """Chave de comparação: NFC, minúsculas e espaços colapsados — o acento fica.

    NFC porque o mesmo `ç` chega composto ou decomposto (NFD), e os dois são a mesma
    negativa para o Google.
    """
    return " ".join(unicodedata.normalize("NFC", texto).lower().split())


def classificar(
    nova: dict[str, Any], existentes: list[dict[str, Any]]
) -> tuple[str, dict[str, Any] | None]:
    """`("repetida", e)`, `("coberta", e)` ou `("nova", None)`.

    `nova` e cada existente têm `text` e `match_type`. Repetida vence coberta.
    """
    alvo = chave(nova["text"])
    amplitude = AMPLITUDE[nova["match_type"]]  # o schema restringe ao enum
    cobre: dict[str, Any] | None = None
    for e in existentes:
        if chave(e["text"]) != alvo:
            continue
        if e["match_type"] == nova["match_type"]:
            return "repetida", e
        if cobre is None and AMPLITUDE.get(e["match_type"], -1) > amplitude:
            cobre = e
    return ("coberta", cobre) if cobre is not None else ("nova", None)
