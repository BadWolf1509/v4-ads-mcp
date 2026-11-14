"""Textos de RSA com pino (G2, spec 2026-11-14): normalizacao e criterio de perda.

Modulo puro (sem I/O), compartilhado pelo builder (`mutates/ads.py`), pelo pre-flight
(`preflight.py`), pelo confirmador (`confirmadores.py`) e pelas tools. Mora em
`google_ads/` e nao em `mcp/tools/` porque a camada Google nao importa da camada MCP;
o schema JSON do item fica em `src/mcp/tools/_rsa_textos.py`, que reexporta isto.

Item de `headlines`/`descriptions` e string (sem pino) ou `{text, pinned_field?}`.
"Perder pino" e por POSICAO (decisao do Wellington, 14/11): perde quem tinha >=1 pino
numa posicao e fica sem nenhum nela. Reescrever o texto mantendo a posicao nao e perda.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

POSICOES_HEADLINE: tuple[str, ...] = ("HEADLINE_1", "HEADLINE_2", "HEADLINE_3")
POSICOES_DESCRIPTION: tuple[str, ...] = ("DESCRIPTION_1", "DESCRIPTION_2")

# Campo do payload -> posicoes que ele aceita. A ordem e a canonica das mensagens.
POSICOES_POR_CAMPO: dict[str, tuple[str, ...]] = {
    "headlines": POSICOES_HEADLINE,
    "descriptions": POSICOES_DESCRIPTION,
}
_ORDEM = {p: i for i, p in enumerate(POSICOES_HEADLINE + POSICOES_DESCRIPTION)}

AVISO_PINO = "Pinar reduz a forca do anuncio: o Google tem menos combinacoes para testar."


def normalizar_textos(itens: list[str | dict[str, Any]]) -> list[dict[str, Any]]:
    """Sempre `{"text", "pinned_field": str | None}`. String e objeto sem pino -> None."""
    saida: list[dict[str, Any]] = []
    for item in itens:
        if isinstance(item, str):
            saida.append({"text": item, "pinned_field": None})
        else:
            saida.append({"text": item["text"], "pinned_field": item.get("pinned_field")})
    return saida


def pinos_por_posicao(itens: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Itens normalizados -> `{posicao: [textos]}`, so posicoes com pino.

    Mesmo shape de `parse_rsa_estado_row(...)["pinos"]`, para comparar pedido e relido.
    """
    pinos: dict[str, list[str]] = {}
    for item in itens:
        pino = item["pinned_field"]
        if pino is not None:
            pinos.setdefault(pino, []).append(item["text"])
    return pinos


def posicoes_perdidas(atuais: Mapping[str, list[str]], novos: Mapping[str, list[str]]) -> list[str]:
    """Posicoes com pino hoje e NENHUM pino na lista nova, na ordem canonica."""
    perdidas = [p for p, textos in atuais.items() if textos and not novos.get(p)]
    return sorted(perdidas, key=lambda p: _ORDEM.get(p, len(_ORDEM)))


def campos_de_texto(spec: Mapping[str, Any]) -> tuple[str, ...]:
    """Quais de `headlines`/`descriptions` o item traz (o update pode trazer um so)."""
    return tuple(c for c in POSICOES_POR_CAMPO if c in spec)


def posicoes_dos_campos(campos: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(p for c in campos for p in POSICOES_POR_CAMPO[c])


def restringir(pinos: Mapping[str, list[str]], posicoes: tuple[str, ...]) -> dict[str, list[str]]:
    """So as posicoes dos campos em jogo: update so de descriptions nao mexe em headline."""
    return {p: list(t) for p, t in pinos.items() if p in posicoes}


def pinos_pedidos(spec: Mapping[str, Any]) -> dict[str, list[str]]:
    """Pinos que o item pede, somando os campos de texto que ele traz."""
    pinos: dict[str, list[str]] = {}
    for campo in campos_de_texto(spec):
        for pos, textos in pinos_por_posicao(normalizar_textos(spec[campo])).items():
            pinos.setdefault(pos, []).extend(textos)
    return pinos


def pinos_por_posicao_total(itens: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Quantos assets pinados por posicao no lote inteiro — contagem, nunca texto.

    E o que vai ao audit (`params_summary`): o audit nao guarda texto de anuncio.
    """
    total: dict[str, int] = {}
    for item in itens:
        for pos, textos in pinos_pedidos(item).items():
            total[pos] = total.get(pos, 0) + len(textos)
    return total
