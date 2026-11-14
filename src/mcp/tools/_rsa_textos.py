"""Schema do item de texto de RSA (G2), compartilhado por create_rsa e update_rsa.

O item e string (sem pino, retrocompativel) ou `{text, pinned_field?}`. O schema do
item NAO tem `type` nem composicao: `oneOf/anyOf/allOf` derrubam a sessao inteira do
gestor (3b.19B.1), e `type` em lista nunca foi medido contra a API (nenhum schema de
producao o usava; guard `test_no_type_array_in_any_schema`). O schema so DESCREVE as
duas formas; quem recusa e `validar_textos`, no corpo da tool, antes do token — a
mitigacao do projeto para regra que o schema nao expressa.

A logica pura (normalizacao, criterio por posicao) mora em `src/google_ads/rsa_textos.py`
e e reexportada aqui.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from src.google_ads.rsa_textos import (
    AVISO_PINO,
    POSICOES_DESCRIPTION,
    POSICOES_HEADLINE,
    POSICOES_POR_CAMPO,
    campos_de_texto,
    normalizar_textos,
    pinos_pedidos,
    pinos_por_posicao,
    posicoes_perdidas,
)

__all__ = [
    "AVISO_PINO",
    "ITEM_TEXTO",
    "LIMITE_PREVIEW_DETALHADO",
    "TETO_LOTE_RSA",
    "POSICOES_DESCRIPTION",
    "POSICOES_HEADLINE",
    "normalizar_textos",
    "pinos_por_posicao",
    "posicoes_perdidas",
    "preview_compacto",
    "preview_do_lote",
    "validar_textos",
]

# Teto de itens por chamada de create_rsa/update_rsa (M2; era 5). Unica fonte: os dois
# schemas usam esta constante.
TETO_LOTE_RSA: int = 50
# Ate aqui o preview e o detalhado de sempre; acima, `preview_compacto`.
LIMITE_PREVIEW_DETALHADO = 5

# Teto de caracteres por campo (era o `maxLength` do schema antes do G2).
MAX_LEN_POR_CAMPO: dict[str, int] = {"headlines": 30, "descriptions": 90}
_CHAVES_DO_OBJETO = frozenset({"text", "pinned_field"})


def ITEM_TEXTO(max_len: int, posicoes: tuple[str, ...]) -> dict[str, Any]:  # noqa: N802 — nome do contrato (brief G2)
    """Item sem `type`: so a descricao das duas formas (a regra vive em `validar_textos`)."""
    return {
        "description": (
            f"String de 1 a {max_len} caracteres (sem pino) OU objeto "
            f'{{"text": <1 a {max_len} caracteres>, "pinned_field": <opcional, um de '
            f"{', '.join(posicoes)}>}} para pinar o texto nessa posicao. Nenhuma outra "
            "chave no objeto."
        )
    }


def _erro_do_item(item: Any, max_len: int, posicoes: tuple[str, ...]) -> str | None:
    if isinstance(item, str):
        texto = item
    elif isinstance(item, Mapping):
        extras = sorted(str(k) for k in item if k not in _CHAVES_DO_OBJETO)
        if extras:
            return f"objeto com chave nao aceita ({', '.join(extras)}); so text e pinned_field"
        if "text" not in item:
            return "objeto sem text"
        texto = item["text"]
        if not isinstance(texto, str):
            return "text tem que ser string"
        if "pinned_field" in item and item["pinned_field"] not in posicoes:
            return (
                f"pinned_field {item['pinned_field']!r} nao vale aqui; use um de "
                f"{', '.join(posicoes)}"
            )
    else:
        return (
            f"item tem que ser string ou objeto {{text, pinned_field}}, veio {type(item).__name__}"
        )
    if not 1 <= len(texto) <= max_len:
        return f"texto com {len(texto)} caracteres; o aceito e de 1 a {max_len}"
    return None


def validar_textos(spec: Mapping[str, Any], rotulo: str) -> str | None:
    """Erro PT-BR do primeiro item invalido de headlines/descriptions, ou None.

    Substitui o que o schema garantia antes do G2 (string 1..30 / 1..90) e acrescenta as
    regras do objeto. `rotulo` nomeia o anuncio na mensagem ("ad_id 123", "RSA 0 ...").
    """
    for campo in campos_de_texto(spec):
        itens = spec[campo]
        if not isinstance(itens, list):
            return f"{rotulo}: {campo} tem que ser lista"
        for i, item in enumerate(itens):
            erro = _erro_do_item(item, MAX_LEN_POR_CAMPO[campo], POSICOES_POR_CAMPO[campo])
            if erro is not None:
                return f"{rotulo}: {campo}[{i}] invalido — {erro}."
    return None


def preview_compacto(updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Preview de update_rsa para lote grande: uma linha curta por anuncio.

    Sem texto, exceto quando `headlines`/`descriptions` MUDAM naquele update; os pinos
    viram contagem (o antes->depois detalhado so existe ate `LIMITE_PREVIEW_DETALHADO`).
    """
    saida: list[dict[str, Any]] = []
    for u in updates:
        item: dict[str, Any] = {
            "ad_id": u["ad_id"],
            "fields_updated": sorted(k for k in u if k not in ("ad_id", "remover_pinos")),
            "contagens": {
                "headlines": len(u.get("headlines", [])),
                "descriptions": len(u.get("descriptions", [])),
                "pinos": sum(len(t) for t in pinos_pedidos(u).values()),
            },
            "final_urls": u.get("final_urls"),
            "path1": u.get("path1"),
            "path2": u.get("path2"),
        }
        for campo in ("headlines", "descriptions"):
            if campo in u:
                item[campo] = u[campo]
        if u.get("remover_pinos", False):
            item["remover_pinos"] = True
        saida.append(item)
    return saida


def preview_do_lote(
    itens: list[dict[str, Any]], detalhado: Callable[[dict[str, Any]], dict[str, Any]]
) -> list[dict[str, Any]]:
    """Ate `LIMITE_PREVIEW_DETALHADO` itens: o preview detalhado atual; acima, o compacto."""
    if len(itens) <= LIMITE_PREVIEW_DETALHADO:
        return [detalhado(i) for i in itens]
    return preview_compacto(itens)
