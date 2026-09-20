"""F184: o efeito de cada operacao, ao lado do veredito do Google.

O Google responde `success` para uma operacao que ele aceitou e NAO executou. Medido
em producao em 20/09 (MO-JP): `update_rsa` com `final_urls` invalida devolveu
`status: "success"` e `failed_count: 0`, e o anuncio ficou intocado. O unico sinal era
o `resource_name` daquela linha vir vazio.

Estes testes cobrem a juncao: `status` continua sendo o veredito do Google, e `efeito`
passa a dizer se a linha MUDOU alguma coisa.
"""

from __future__ import annotations

from typing import Any

from src.google_ads.mutations import anotar_efeito_por_operacao


def _op(idx: int, status: str) -> dict[str, Any]:
    return {"index": idx, "status": status, "error": None if status == "success" else "erro"}


def test_op_que_mudou_algo_e_marcada_como_mudou() -> None:
    anotadas = anotar_efeito_por_operacao(
        [_op(0, "success")],
        ["customers/123/ads/456"],
    )
    assert anotadas[0]["efeito"] == "mudou"


def test_op_aplicada_sem_mudar_nada_e_marcada_sem_efeito() -> None:
    """O caso do F184: o Google disse sucesso e nao executou.

    Sem esta anotacao, a unica denuncia e o `resource_names[i]` vazio, que vive em
    outro campo da resposta e nao na linha que afirma o sucesso.
    """
    anotadas = anotar_efeito_por_operacao(
        [_op(0, "success"), _op(1, "success")],
        ["customers/123/ads/456", None],
    )
    assert anotadas[0]["efeito"] == "mudou"
    assert anotadas[1]["efeito"] == "sem_efeito"
    # O veredito do Google NAO e reescrito: quem diz "falhou" e o `status`, e a op 1
    # nao falhou — ela nao teve efeito. Sao coisas diferentes (contraste com o F139,
    # que decidiu chamar o no-op legitimo de sucesso).
    assert anotadas[1]["status"] == "success"


def test_op_que_falhou_nao_recebe_efeito() -> None:
    """Falhou: o efeito nao e pergunta, e o `status` ja responde."""
    anotadas = anotar_efeito_por_operacao(
        [_op(0, "failed")],
        [None],
    )
    assert anotadas[0]["efeito"] is None
    assert anotadas[0]["status"] == "failed"


def test_sem_resource_names_o_efeito_e_desconhecido_e_nao_sem_efeito() -> None:
    """Rede de seguranca contra drift de SDK: nao sei != nao mudou.

    `_extract_resource_names` devolve [] quando o campo some da resposta. Marcar tudo
    como `sem_efeito` ali seria inventar uma afirmacao a partir de uma ausencia — o
    erro exato que o F184 denuncia, so que do nosso lado.
    """
    anotadas = anotar_efeito_por_operacao(
        [_op(0, "success"), _op(1, "success")],
        [],
    )
    assert anotadas[0]["efeito"] is None
    assert anotadas[1]["efeito"] is None
