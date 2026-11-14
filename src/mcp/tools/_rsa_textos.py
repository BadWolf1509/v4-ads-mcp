"""Schema do item de texto de RSA (G2), compartilhado por create_rsa e update_rsa.

O item e string (sem pino, retrocompativel) ou `{text, pinned_field?}`. O desenho do
brief pedia `oneOf: [string, objeto]`, mas `oneOf/anyOf/allOf` em `input_schema`
derruba a sessao inteira do gestor (3b.19B.1, guard
`test_no_composition_keywords_in_any_schema`). A mesma regra sai sem composicao:
`type: ["string", "object"]` — `minLength`/`maxLength` so valem para string, e
`properties`/`required`/`additionalProperties` so para objeto (JSON Schema 2020-12).

A logica pura (normalizacao, criterio por posicao) mora em `src/google_ads/rsa_textos.py`
e e reexportada aqui.
"""

from __future__ import annotations

from typing import Any

from src.google_ads.rsa_textos import (
    AVISO_PINO,
    POSICOES_DESCRIPTION,
    POSICOES_HEADLINE,
    normalizar_textos,
    pinos_por_posicao,
    posicoes_perdidas,
)

__all__ = [
    "AVISO_PINO",
    "ITEM_TEXTO",
    "POSICOES_DESCRIPTION",
    "POSICOES_HEADLINE",
    "normalizar_textos",
    "pinos_por_posicao",
    "posicoes_perdidas",
]


def ITEM_TEXTO(max_len: int, posicoes: tuple[str, ...]) -> dict[str, Any]:  # noqa: N802 — nome do contrato (brief G2)
    """JSON schema do item: string de 1..max_len ou `{text, pinned_field?}`."""
    return {
        "type": ["string", "object"],
        "minLength": 1,
        "maxLength": max_len,
        "properties": {
            "text": {"type": "string", "minLength": 1, "maxLength": max_len},
            "pinned_field": {"type": "string", "enum": list(posicoes)},
        },
        "required": ["text"],
        "additionalProperties": False,
    }
