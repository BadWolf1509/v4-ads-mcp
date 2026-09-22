"""Sob leitura nao-medida, o Customer Match diz que nao sabe — nao que deu tudo certo."""

from src.google_ads.customer_match import _Progresso


def test_sem_medicao_os_tres_campos_dizem_desconhecido_juntos() -> None:
    """`null` ao lado de `0` le como zero. Tres campos que descrevem a mesma
    coisa desconhecida tem que dizer desconhecido JUNTOS — e a regra que o
    `get_ad_schedule` ja aplica no bloco do F147."""
    p = _Progresso(create_id="a", add_id="b", membros_recusados=None)
    assert p.submetidos(500) is None, "lote de 500 sem medicao nao e '500 aceitos'"


def test_com_medicao_o_calculo_continua_o_mesmo() -> None:
    """CONTROLE POSITIVO: sem ele, uma implementacao que devolve None sempre
    passaria no teste de cima."""
    p = _Progresso(create_id="a", add_id="b", membros_recusados=[{"index": 1}])
    assert p.submetidos(500) == 499


def test_parada_antes_do_passo_2_continua_zero() -> None:
    """`pii_anexada` False vence: nao houve resposta do add, entao nao ha o que
    medir E nada saiu. Zero e a verdade aqui, nao 'desconhecido'."""
    p = _Progresso(create_id="a", membros_recusados=None)
    assert p.submetidos(500) == 0
