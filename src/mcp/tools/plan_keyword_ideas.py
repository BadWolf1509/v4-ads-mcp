# bucket: defer
"""Tool: plan_keyword_ideas - ideias do Planejador de palavras-chave por origem e cidade.

Uma chamada ao Google por origem x cidade (fato 3 do desenho: `url_seed` junto de
sementes derruba a lista de ~1.900 para 40). Cada ideia diz de onde veio.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from google.ads.googleads.errors import GoogleAdsException

from src.google_ads.cidades import (
    Cidade,
    CidadeNaoResolvida,
    escolher_cidade,
    rotulo,
    separar_uf,
)
from src.google_ads.errors import to_friendly
from src.google_ads.keyword_planning import run_keyword_planning
from src.google_ads.planejador import (
    Metricas,
    metricas_do_proto,
    normalizar_termo,
    ordenar_e_cortar,
    unir,
    volume_maximo,
)
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_OPERACAO = "plan_keyword_ideas"
_IDIOMA = "languageConstants/1014"
_BRASIL = "geoTargetConstants/2076"
_REDE = "GOOGLE_SEARCH"
_CHAVE_BRASIL = "Brasil"
# Erros que derrubam a requisicao inteira: a proxima chamada falharia igual.
_CODIGOS_FATAIS = frozenset({"QUOTA_ERROR", "AUTHORIZATION_ERROR", "AUTHENTICATION_ERROR"})

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "sementes": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "maxItems": 20,
        },
        "site": {"type": "string", "format": "uri"},
        "concorrentes": {
            "type": "array",
            "items": {"type": "string", "format": "uri"},
            "maxItems": 5,
        },
        "cidades": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "maxItems": 5,
        },
        "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}

# (origem, sementes | None, url | None)
_Origem = tuple[str, list[str] | None, str | None]


def _dominio(url: str) -> str:
    host = urlparse(url).netloc or url
    return host.removeprefix("www.")


@dataclass
class _Resultado:
    cidades: list[Cidade] = field(default_factory=list)
    lotes: list[tuple[str, str, list[tuple[str, Metricas]]]] = field(default_factory=list)
    falhas: list[dict[str, Any]] = field(default_factory=list)
    nao_resolvida: CidadeNaoResolvida | None = None


def _resolver_cidades(client: Any, pedidos: list[str]) -> list[Cidade]:
    partes = [separar_uf(p) for p in pedidos]
    svc = client.get_service("GeoTargetConstantService")
    req = client.get_type("SuggestGeoTargetConstantsRequest")
    req.locale = "pt"
    req.country_code = "BR"
    req.location_names.names.extend(nome for nome, _ in partes)
    resp = svc.suggest_geo_target_constants(request=req)
    sugestoes = list(resp.geo_target_constant_suggestions)
    cidades: list[Cidade] = []
    for nome, uf in partes:
        alvo = normalizar_termo(nome)
        # `search_term` diz a qual nome pedido a sugestao responde; sem ele em
        # nenhuma sugestao, a lista toda e dos candidatos.
        rotuladas = any(s.search_term for s in sugestoes)
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


def _ideias_da_origem(
    client: Any,
    customer_id: str,
    geo: str,
    *,
    sementes: list[str] | None,
    url: str | None,
) -> list[tuple[str, Metricas]]:
    svc = client.get_service("KeywordPlanIdeaService")
    req = client.get_type("GenerateKeywordIdeasRequest")
    req.customer_id = customer_id
    req.language = _IDIOMA
    req.geo_target_constants.append(geo)
    req.keyword_plan_network = client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
    req.page_size = 1000
    if sementes is not None:
        req.keyword_seed.keywords.extend(sementes)
    else:
        req.url_seed.url = url
    itens: list[tuple[str, Metricas]] = []
    for r in svc.generate_keyword_ideas(request=req):
        m = r.keyword_idea_metrics if "keyword_idea_metrics" in r else None
        itens.append((r.text, metricas_do_proto(m)))
    return itens


def _montar_chamadas(
    customer_id: str, pedidos: list[str], origens: list[_Origem]
) -> Callable[[Any], _Resultado]:
    def chamadas(client: Any) -> _Resultado:
        res = _Resultado()
        try:
            res.cidades = _resolver_cidades(client, pedidos) if pedidos else []
        except CidadeNaoResolvida as e:
            res.nao_resolvida = e
            return res
        alvos = (
            [(rotulo(c), c.resource_name) for c in res.cidades]
            if res.cidades
            else [(_CHAVE_BRASIL, _BRASIL)]
        )
        for origem, sementes, url in origens:
            for chave, geo in alvos:
                try:
                    itens = _ideias_da_origem(client, customer_id, geo, sementes=sementes, url=url)
                except GoogleAdsException as e:
                    friendly = to_friendly(e)
                    if sementes is not None or friendly.code in _CODIGOS_FATAIS:
                        raise
                    res.falhas.append({"origem": origem, "cidade": chave, "erro": str(friendly)})
                    continue
                res.lotes.append((origem, chave, itens))
        return res

    return chamadas


def _erro(mensagem: str) -> dict[str, Any]:
    return {"status": "error", "error_message": mensagem, "operation": _OPERACAO}


@register_tool(
    name="plan_keyword_ideas",
    description=(
        "[DEFER] Ideias de palavras-chave do Planejador do Google a partir de sementes, do site "
        "do cliente e de sites de concorrentes, com volume, concorrência, faixa de CPC e "
        "sazonalidade. O volume vem em degraus do Google (10, 20, 50, 110...), não é exato; "
        "`null` significa que o Google não tem dado, não zero. O CPC é estimativa de topo de "
        "página, uma faixa (`cpc_topo_min_brl` a `cpc_topo_max_brl`), não o que a conta paga; "
        "os campos _brl assumem conta BRL. O resultado não depende da conta usada: use qualquer "
        "conta sua (ex.: a interna 6728568947). Site e concorrentes ampliam a lista por origem: "
        "cada ideia traz `origens` (semente, site, concorrente:<domínio>), e ideias vindas de "
        "URL podem fugir do negócio, então filtre por origem. Cidades por nome, com UF para "
        "desambiguar (ex.: 'João Pessoa, PB'), até 5; sem cidade o recorte é o Brasil. As "
        "métricas vêm por cidade em `por_cidade`, sem soma entre cidades. Ordem por maior "
        "volume; `limit` (padrão 200, máximo 1000) corta a cauda e `truncated` avisa. Uma "
        "origem de URL que falha não derruba as outras: aparece em `origens_com_falha`."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def plan_keyword_ideas(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id: str = args["customer_id"]
    sementes: list[str] = list(args.get("sementes") or [])
    site: str | None = args.get("site")
    concorrentes: list[str] = list(args.get("concorrentes") or [])
    pedidos: list[str] = list(args.get("cidades") or [])
    limit = int(args.get("limit", 200))
    if not (sementes or site or concorrentes):
        return _erro("Informe pelo menos um entre `sementes`, `site` e `concorrentes`.")

    origens: list[_Origem] = []
    if sementes:
        origens.append(("semente", sementes, None))
    if site:
        origens.append(("site", None, site))
    for url in concorrentes:
        origens.append((f"concorrente:{_dominio(url)}", None, url))

    estimated_ops = (1 if pedidos else 0) + len(origens) * max(1, len(pedidos))
    resultado: _Resultado = await run_keyword_planning(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        operation_name=_OPERACAO,
        estimated_ops=estimated_ops,
        params_summary={
            "sementes": len(sementes),
            "site": _dominio(site) if site else None,
            "concorrentes": [_dominio(u) for u in concorrentes],
            "cidades": pedidos,
            "limit": limit,
        },
        chamadas=_montar_chamadas(customer_id, pedidos, origens),
    )
    if resultado.nao_resolvida is not None:
        e = resultado.nao_resolvida
        cand = "; ".join(e.candidatos) if e.candidatos else "nenhum"
        return _erro(
            f"Não achei uma cidade para {e.pedido!r}. Candidatos do Google: {cand}. "
            "Confira o nome ou acrescente a UF (ex.: 'Campina Grande, PB')."
        )

    avisos = [
        f"cidade pedida '{c.pedido}' resolvida como '{c.nome}'"
        for c in resultado.cidades
        if c.nome_difere
    ]
    todas = unir(resultado.lotes)
    ideias, truncated = ordenar_e_cortar(todas, limit)
    cidades_recorte: Any = (
        [
            {
                "pedido": c.pedido,
                "resource_name": c.resource_name,
                "canonical_name": c.canonical_name,
                "rotulo": rotulo(c),
            }
            for c in resultado.cidades
        ]
        if resultado.cidades
        else f"Brasil ({_BRASIL})"
    )
    return {
        "customer_id": customer_id,
        "recorte": {"cidades": cidades_recorte, "idioma": _IDIOMA, "rede": _REDE},
        "volume_em_degraus": True,
        "ideias": [
            {
                "termo": i.termo,
                "origens": i.origens,
                "volume_maximo": volume_maximo(i),
                "por_cidade": i.por_cidade,
            }
            for i in ideias
        ],
        "total_ideias": len(todas),
        "truncated": truncated,
        "origens_com_falha": resultado.falhas,
        "avisos": avisos,
    }
