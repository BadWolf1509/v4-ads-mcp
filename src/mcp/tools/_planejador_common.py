"""Pecas compartilhadas pelas tools do Planejador de palavras-chave (so Google).

Resolucao de cidade por nome (uma chamada `suggest_geo_target_constants`), constantes do
recorte e o envelope de erro de cidade nao resolvida.
"""

from __future__ import annotations

from typing import Any

from src.google_ads.cidades import (
    Cidade,
    CidadeNaoResolvida,
    escolher_cidade,
    rotulo,
    separar_uf,
)
from src.google_ads.errors import GoogleAdsFriendlyError
from src.google_ads.planejador import normalizar_termo

IDIOMA = "languageConstants/1014"
BRASIL = "geoTargetConstants/2076"
REDE = "GOOGLE_SEARCH"
CHAVE_BRASIL = "Brasil"
CODIGO_CIDADE = "CIDADE_NAO_RESOLVIDA"
# Erros que derrubam a requisicao inteira: a proxima chamada falharia igual.
CODIGOS_FATAIS = frozenset({"QUOTA_ERROR", "AUTHORIZATION_ERROR", "AUTHENTICATION_ERROR"})


def nao_resolvida(e: CidadeNaoResolvida) -> GoogleAdsFriendlyError:
    cand = "; ".join(e.candidatos) if e.candidatos else "nenhum"
    return GoogleAdsFriendlyError(
        f"Não achei uma cidade para {e.pedido!r}. Candidatos do Google: {cand}. "
        "Confira o nome ou acrescente a UF (ex.: 'Campina Grande, PB').",
        code=CODIGO_CIDADE,
        original=e,
    )


def resolver_cidades(client: Any, pedidos: list[str]) -> list[Cidade]:
    partes = [separar_uf(p) for p in pedidos]
    svc = client.get_service("GeoTargetConstantService")
    req = client.get_type("SuggestGeoTargetConstantsRequest")
    req.locale = "pt"
    req.country_code = "BR"
    req.location_names.names.extend(nome for nome, _ in partes)
    resp = svc.suggest_geo_target_constants(request=req)
    sugestoes = list(resp.geo_target_constant_suggestions)
    # `search_term` ecoa o nome pedido (medido em 29/10): diz a qual pedido cada
    # sugestao responde.
    rotuladas = any(s.search_term for s in sugestoes)
    if not rotuladas and len(partes) > 1:
        raise CidadeNaoResolvida(
            ", ".join(nome for nome, _ in partes),
            [s.geo_target_constant.canonical_name for s in sugestoes],
        )
    cidades: list[Cidade] = []
    for nome, uf in partes:
        alvo = normalizar_termo(nome)
        dele = [s for s in sugestoes if normalizar_termo(s.search_term) == alvo]
        try:
            cidades.append(escolher_cidade(nome, uf, dele if rotuladas else sugestoes))
        except CidadeNaoResolvida as e:
            if dele:
                raise
            # nenhuma sugestao respondeu a este nome: mostra o que o Google devolveu
            raise CidadeNaoResolvida(
                e.pedido, [s.geo_target_constant.canonical_name for s in sugestoes]
            ) from e
    return cidades


def resolver_unicas(client: Any, pedidos: list[str]) -> tuple[list[Cidade], list[str]]:
    """Resolve e deduplica por `resource_name`; devolve `(cidades, avisos)`.

    Cidade nao resolvida sobe como `GoogleAdsFriendlyError(CIDADE_NAO_RESOLVIDA)`: dentro
    do closure do executor, ele audita "error" e nao cobra a quota reservada.
    """
    try:
        resolvidas = resolver_cidades(client, pedidos) if pedidos else []
    except CidadeNaoResolvida as e:
        raise nao_resolvida(e) from e
    vistas: set[str] = set()
    cidades: list[Cidade] = []
    avisos: list[str] = []
    for c in resolvidas:
        if c.resource_name in vistas:
            avisos.append(f"cidade repetida ignorada: '{c.pedido}' ({rotulo(c)})")
            continue
        vistas.add(c.resource_name)
        cidades.append(c)
    return cidades, avisos


def alvos(cidades: list[Cidade]) -> list[tuple[str, str]]:
    """`(chave, geo)` por cidade; sem cidade, o Brasil."""
    return [(rotulo(c), c.resource_name) for c in cidades] or [(CHAVE_BRASIL, BRASIL)]


def avisos_nome_difere(cidades: list[Cidade]) -> list[str]:
    return [
        f"cidade pedida '{c.pedido}' resolvida como '{c.nome}'" for c in cidades if c.nome_difere
    ]


def recorte_cidades(cidades: list[Cidade]) -> Any:
    if not cidades:
        return f"Brasil ({BRASIL})"
    return [
        {
            "pedido": c.pedido,
            "resource_name": c.resource_name,
            "canonical_name": c.canonical_name,
            "rotulo": rotulo(c),
        }
        for c in cidades
    ]


def erro(operacao: str, mensagem: str) -> dict[str, Any]:
    return {"status": "error", "error_message": mensagem, "operation": operacao}
