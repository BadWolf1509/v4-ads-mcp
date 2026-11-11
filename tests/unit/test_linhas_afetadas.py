"""`linhas_afetadas`: contagem do command tag do `execute` do asyncpg."""

import pytest

from src.db.repositories._comum import linhas_afetadas


@pytest.mark.parametrize(
    ("status", "esperado"),
    [("UPDATE 3", 3), ("INSERT 0 2", 2), ("DELETE 0", 0), ("DELETE 12", 12)],
)
def test_ultimo_token_e_a_contagem(status: str, esperado: int) -> None:
    assert linhas_afetadas(status) == esperado


@pytest.mark.parametrize("status", ["", "UPDATE", "UPDATE x", "INSERT 0 "])
def test_tag_malformada_levanta_em_vez_de_virar_zero(status: str) -> None:
    with pytest.raises(ValueError):
        linhas_afetadas(status)
