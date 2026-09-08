"""O primitivo do corte: um lugar só decide, e o contrato do `+1` fica escrito."""

from src.mcp.tools._common import aplicar_limite


def test_corta_e_declara_quando_veio_sobra() -> None:
    linhas, truncado = aplicar_limite([1, 2, 3, 4], 3)
    assert linhas == [1, 2, 3]
    assert truncado is True


def test_nao_declara_quando_coube_exato() -> None:
    linhas, truncado = aplicar_limite([1, 2, 3], 3)
    assert linhas == [1, 2, 3]
    assert truncado is False


def test_nao_declara_quando_veio_menos() -> None:
    assert aplicar_limite([1], 3) == ([1], False)


def test_lista_vazia() -> None:
    assert aplicar_limite([], 10) == ([], False)


def test_o_truncado_e_bool_de_verdade() -> None:
    """`len(x) > n` já devolve bool; a asserção prende contra um refactor que
    devolva o inteiro da diferença e passe por verdade acidental no consumidor."""
    _, truncado = aplicar_limite([1, 2], 1)
    assert truncado is True
    assert isinstance(truncado, bool)
