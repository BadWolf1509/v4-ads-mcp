"""Resolucao de cidade por nome para o planejador de palavras-chave (puro).

O gestor digita "Joao Pessoa, PB"; o Google quer um `geoTargetConstants/N`.
`suggest_geo_target_constants` devolve cidades, bairros, estados e CEPs misturados
e a ordem nao respeita o estado — por isso a escolha e: so `City`, e com UF so a
que fecha com o estado pedido. Nunca resolve em silencio para outro nome:
`Cidade.nome_difere` marca o caso para quem monta o aviso.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

# sigla -> parte de estado do canonical_name, como o Google escreve (GAQL, 29/10).
UF_PARA_ESTADO: dict[str, str] = {
    "AC": "State of Acre",
    "AL": "State of Alagoas",
    "AP": "State of Amapa",
    "AM": "State of Amazonas",
    "BA": "State of Bahia",
    "CE": "Ceara",
    "DF": "Federal District",
    "ES": "State of Espirito Santo",
    "GO": "State of Goias",
    "MA": "State of Maranhao",
    "MT": "State of Mato Grosso",
    "MS": "State of Mato Grosso do Sul",
    "MG": "State of Minas Gerais",
    "PA": "State of Para",
    "PB": "State of Paraiba",
    "PR": "State of Parana",
    "PE": "State of Pernambuco",
    "PI": "State of Piaui",
    "RJ": "State of Rio de Janeiro",
    "RN": "State of Rio Grande do Norte",
    "RS": "State of Rio Grande do Sul",
    "RO": "State of Rondonia",
    "RR": "State of Roraima",
    "SC": "State of Santa Catarina",
    "SP": "State of Sao Paulo",
    "SE": "State of Sergipe",
    "TO": "State of Tocantins",
}


def _normalizar(texto: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    return " ".join(sem_acento.lower().split())


def _sem_prefixo_estado(estado: str) -> str:
    n = _normalizar(estado)
    return n.removeprefix("state of ")


# nome normalizado (portugues ou o do Google) -> sigla
_NOME_PARA_UF: dict[str, str] = {}
for _uf, _estado in UF_PARA_ESTADO.items():
    _NOME_PARA_UF[_normalizar(_estado)] = _uf
    _NOME_PARA_UF[_sem_prefixo_estado(_estado)] = _uf
_NOME_PARA_UF["distrito federal"] = "DF"

_ESTADO_PARA_UF: dict[str, str] = {_normalizar(e): uf for uf, e in UF_PARA_ESTADO.items()}

_SEPARADOR = re.compile(r"\s*,\s*|\s+-\s+")


def _uf_de(texto: str) -> str | None:
    t = texto.strip()
    if t.upper() in UF_PARA_ESTADO:
        return t.upper()
    return _NOME_PARA_UF.get(_normalizar(t))


def separar_uf(entrada: str) -> tuple[str, str | None]:
    """`"Joao Pessoa, PB"` -> `("Joao Pessoa", "PB")`; sem estado reconhecido -> `None`."""
    texto = entrada.strip()
    partes = _SEPARADOR.split(texto)
    if len(partes) >= 2:
        uf = _uf_de(partes[-1])
        if uf is not None:
            cidade = texto[: texto.rfind(partes[-1])].rstrip(" ,-").strip()
            return cidade, uf
    return texto, None


@dataclass(frozen=True)
class Cidade:
    pedido: str
    resource_name: str
    nome: str
    canonical_name: str

    @property
    def nome_difere(self) -> bool:
        """O Google resolveu para um nome diferente do pedido (ex.: Campina Grande do Sul)."""
        return _normalizar(self.nome) != _normalizar(self.pedido)


class CidadeNaoResolvida(ValueError):  # noqa: N818 - nome fixado pelo desenho
    def __init__(self, pedido: str, candidatos: list[str]) -> None:
        self.pedido = pedido
        self.candidatos = candidatos
        super().__init__(f"Nenhuma cidade encontrada para {pedido!r}. Candidatos: {candidatos}")


def escolher_cidade(pedido: str, uf: str | None, sugestoes: Sequence[Any]) -> Cidade:
    """Primeiro `City` das sugestoes; com `uf`, o primeiro `City` daquele estado."""
    candidatos = [s.geo_target_constant.canonical_name for s in sugestoes]
    sufixo: str | None = None
    if uf is not None:
        estado = UF_PARA_ESTADO.get(uf.strip().upper())
        if estado is None:
            raise CidadeNaoResolvida(pedido, candidatos)
        sufixo = f",{estado},Brazil"
    for s in sugestoes:
        g = s.geo_target_constant
        if g.target_type != "City":
            continue
        if sufixo is not None and not g.canonical_name.endswith(sufixo):
            continue
        return Cidade(
            pedido=pedido,
            resource_name=g.resource_name,
            nome=g.name,
            canonical_name=g.canonical_name,
        )
    raise CidadeNaoResolvida(pedido, candidatos)


def rotulo(c: Cidade) -> str:
    """`"Joao Pessoa (PB)"`: nome + sigla derivada do canonical_name; sem estado, so o nome."""
    partes = c.canonical_name.split(",")
    if len(partes) >= 3:
        uf = _ESTADO_PARA_UF.get(_normalizar(partes[-2]))
        if uf is not None:
            return f"{c.nome} ({uf})"
    return c.nome
