"""Regras puras das negativas (spec 2026-10-05, §3.1).

O Google não aplica variante próxima em negativa (medido na MO-JP, 05/10): `material de
construção` deixou passar `material de construcao`. Acento distingue negativa — por isso a
`chave` o mantém e a `sem_acento` sugere o par.
"""

from __future__ import annotations

import pytest

from src.google_ads.negativas import chave, classificar, sem_acento


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("material de construção", "material de construcao"),
        ("macaco hidráulico", "macaco hidraulico"),
        ("LOCAÇÃO", "LOCACAO"),
        ("aluguel  de  andaime", None),  # sem acento: nada a sugerir, espaço preservado
        ("andaime", None),
    ],
)
def test_sem_acento(texto: str, esperado: str | None) -> None:
    assert sem_acento(texto) == esperado


def test_sem_acento_preserva_caixa_e_espacos() -> None:
    assert sem_acento("Construção  Civil") == "Construcao  Civil"


def test_chave_mantem_acento_e_normaliza_caixa_e_espaco() -> None:
    assert chave("  Material   de Construção ") == "material de construção"
    assert chave("material de construcao") != chave("material de construção")


def _neg(texto: str, tipo: str) -> dict[str, str]:
    return {"text": texto, "match_type": tipo, "criterion_id": "1"}


def test_mesmo_texto_mesmo_tipo_e_repetida() -> None:
    existente = _neg("Patrol", "PHRASE")
    assert classificar({"text": "patrol", "match_type": "PHRASE"}, [existente]) == (
        "repetida",
        existente,
    )


@pytest.mark.parametrize(
    ("nova", "existente"),
    [("PHRASE", "BROAD"), ("EXACT", "BROAD"), ("EXACT", "PHRASE")],
)
def test_tipo_mais_estreito_contra_mais_amplo_e_coberta(nova: str, existente: str) -> None:
    e = _neg("patrol", existente)
    assert classificar({"text": "patrol", "match_type": nova}, [e]) == ("coberta", e)


@pytest.mark.parametrize(
    ("nova", "existente"),
    [("BROAD", "PHRASE"), ("BROAD", "EXACT"), ("PHRASE", "EXACT")],
)
def test_tipo_mais_amplo_contra_mais_estreito_e_nova(nova: str, existente: str) -> None:
    assert classificar({"text": "patrol", "match_type": nova}, [_neg("patrol", existente)]) == (
        "nova",
        None,
    )


def test_repetida_vence_coberta_quando_as_duas_existem() -> None:
    igual = _neg("patrol", "PHRASE")
    ampla = _neg("patrol", "BROAD")
    assert classificar({"text": "patrol", "match_type": "PHRASE"}, [ampla, igual]) == (
        "repetida",
        igual,
    )


def test_textos_diferentes_nao_se_comparam() -> None:
    """Plural, acento e texto contido não são tratados (spec §2, fora de escopo)."""
    existentes = [_neg("material", "BROAD"), _neg("construção", "BROAD")]
    assert classificar({"text": "materiais", "match_type": "BROAD"}, existentes) == ("nova", None)
    assert classificar({"text": "construcao", "match_type": "BROAD"}, existentes) == ("nova", None)
    assert classificar({"text": "material de x", "match_type": "BROAD"}, existentes) == (
        "nova",
        None,
    )
