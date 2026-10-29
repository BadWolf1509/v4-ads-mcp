"""Resolucao de cidade por nome para o planejador (puro, sem rede)."""

from __future__ import annotations

import pytest
from google.ads.googleads.v25.resources.types.geo_target_constant import (
    GeoTargetConstant,
)
from google.ads.googleads.v25.services.types.geo_target_constant_service import (
    GeoTargetConstantSuggestion,
)

from src.google_ads.cidades import (
    UF_PARA_ESTADO,
    Cidade,
    CidadeNaoResolvida,
    escolher_cidade,
    rotulo,
    separar_uf,
)


def _sug(id_: int, nome: str, tipo: str, canonical: str) -> GeoTargetConstantSuggestion:
    # Valores copiados do repr medido na Task 1 (sonda de 29/10).
    return GeoTargetConstantSuggestion(
        geo_target_constant=GeoTargetConstant(
            resource_name=f"geoTargetConstants/{id_}",
            id=id_,
            name=nome,
            country_code="BR",
            target_type=tipo,
            canonical_name=canonical,
        ),
    )


JOAO_PESSOA = [
    _sug(1001622, "João Pessoa", "City", "Joao Pessoa,State of Paraiba,Brazil"),
    _sug(9248071, "João Pessoa", "Neighborhood", "Joao Pessoa,State of Santa Catarina,Brazil"),
    _sug(20098, "Paraíba", "State", "State of Paraiba,Brazil"),
    _sug(20096, "Mato Grosso", "State", "State of Mato Grosso,Brazil"),
    _sug(9218594, "89270-000", "Postal Code", "89270-000,State of Santa Catarina,Brazil"),
    _sug(1032000, "Santa Rita", "City", "Santa Rita,State of Paraiba,Brazil"),
    _sug(9101443, "58013", "Postal Code", "58013,State of Paraiba,Brazil"),
]

CAMPINA_GRANDE = [
    _sug(1001621, "Campina Grande", "City", "Campina Grande,State of Paraiba,Brazil"),
    _sug(
        1031525,
        "Campina Grande do Sul",
        "City",
        "Campina Grande do Sul,State of Parana,Brazil",
    ),
    _sug(
        9074149,
        "Campina Grande do Sul",
        "City",
        "Campina Grande do Sul,Campina Grande do Sul,State of Parana,Brazil",
    ),
    _sug(20098, "Paraíba", "State", "State of Paraiba,Brazil"),
    _sug(1001729, "Campinas", "City", "Campinas,State of Sao Paulo,Brazil"),
]


def test_joao_pessoa_escolhe_city_pb() -> None:
    c = escolher_cidade("João Pessoa", None, JOAO_PESSOA)
    assert c.resource_name == "geoTargetConstants/1001622"
    assert c.nome == "João Pessoa"
    assert c.canonical_name == "Joao Pessoa,State of Paraiba,Brazil"


def test_campina_grande_sem_uf_pega_primeiro_city() -> None:
    c = escolher_cidade("Campina Grande", None, CAMPINA_GRANDE)
    assert c.resource_name == "geoTargetConstants/1001621"


def test_campina_grande_com_uf_pr_pega_do_sul_e_avisa_nome_diferente() -> None:
    c = escolher_cidade("Campina Grande", "PR", CAMPINA_GRANDE)
    assert c.resource_name == "geoTargetConstants/1031525"
    assert c.nome_difere is True


def test_nome_sem_acento_nao_difere() -> None:
    c = escolher_cidade("Joao  Pessoa", None, JOAO_PESSOA)
    assert c.nome == "João Pessoa"
    assert c.nome_difere is False


def test_bairro_e_cep_nunca_vencem() -> None:
    so_lixo = [JOAO_PESSOA[1], JOAO_PESSOA[2], JOAO_PESSOA[4]]
    with pytest.raises(CidadeNaoResolvida) as exc:
        escolher_cidade("João Pessoa", None, so_lixo)
    assert exc.value.pedido == "João Pessoa"
    assert exc.value.candidatos == [
        "Joao Pessoa,State of Santa Catarina,Brazil",
        "State of Paraiba,Brazil",
        "89270-000,State of Santa Catarina,Brazil",
    ]


def test_uf_sem_city_naquele_estado_nao_resolve() -> None:
    with pytest.raises(CidadeNaoResolvida):
        escolher_cidade("João Pessoa", "SP", JOAO_PESSOA)


def test_uf_desconhecida_nao_resolve() -> None:
    with pytest.raises(CidadeNaoResolvida):
        escolher_cidade("João Pessoa", "XX", JOAO_PESSOA)


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("João Pessoa, PB", ("João Pessoa", "PB")),
        ("João Pessoa - pb", ("João Pessoa", "PB")),
        ("Campina Grande, Paraíba", ("Campina Grande", "PB")),
        ("Campina Grande, Paraiba", ("Campina Grande", "PB")),
        ("Recife", ("Recife", None)),
        ("Brasília, Distrito Federal", ("Brasília", "DF")),
        ("Fortaleza, Ceará", ("Fortaleza", "CE")),
        ("São Paulo, State of Sao Paulo", ("São Paulo", "SP")),
        ("Pau dos Ferros - Rio Grande do Norte", ("Pau dos Ferros", "RN")),
    ],
)
def test_separar_uf(entrada: str, esperado: tuple[str, str | None]) -> None:
    assert separar_uf(entrada) == esperado


def test_uf_para_estado_cobre_27_como_o_google_escreve() -> None:
    assert len(UF_PARA_ESTADO) == 27
    assert UF_PARA_ESTADO["PB"] == "State of Paraiba"
    assert UF_PARA_ESTADO["CE"] == "Ceara"
    assert UF_PARA_ESTADO["DF"] == "Federal District"


def test_rotulo() -> None:
    c = escolher_cidade("João Pessoa", None, JOAO_PESSOA)
    assert rotulo(c) == "João Pessoa (PB)"
    assert rotulo(escolher_cidade("Campinas", "SP", CAMPINA_GRANDE)) == "Campinas (SP)"


def test_rotulo_sem_estado_derivavel_e_so_o_nome() -> None:
    c = Cidade(
        pedido="X", resource_name="geoTargetConstants/1", nome="Xis", canonical_name="Xis,Brazil"
    )
    assert rotulo(c) == "Xis"
