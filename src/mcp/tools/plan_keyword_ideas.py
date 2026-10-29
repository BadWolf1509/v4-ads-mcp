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

from src.google_ads.cidades import Cidade
from src.google_ads.errors import GoogleAdsFriendlyError, to_friendly
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
from src.mcp.tools import _planejador_common as comum
from src.mcp.tools._registry import register_tool

_OPERACAO = "plan_keyword_ideas"

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "sementes": {
            "type": "array",
            # 80: limite do Google para uma palavra-chave.
            "items": {"type": "string", "minLength": 1, "maxLength": 80},
            "maxItems": 20,
        },
        "site": {"type": "string", "minLength": 1, "maxLength": 2048},
        "concorrentes": {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 2048},
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


def _com_esquema(url: str) -> str:
    """`mestredaobra.com.br` -> `https://mestredaobra.com.br`; o Google quer URL completa."""
    u = url.strip()
    return u if "://" in u else f"https://{u}"


def _dominio(url: str) -> str:
    return urlparse(_com_esquema(url)).netloc.lower().removeprefix("www.")


def _concorrentes_unicos(site: str | None, concorrentes: list[str]) -> tuple[list[str], list[str]]:
    """Concorrentes sem repeticao por dominio (e sem o proprio site), com um aviso por descarte."""
    vistos: dict[str, str] = {}
    if site:
        vistos[_dominio(site)] = site
    saida: list[str] = []
    avisos: list[str] = []
    for url in concorrentes:
        d = _dominio(url)
        if d in vistos:
            avisos.append(
                f"concorrente '{url}' repetido de '{vistos[d]}' (mesmo domínio), ignorado"
            )
            continue
        vistos[d] = url
        saida.append(url)
    return saida, avisos


@dataclass
class _Resultado:
    cidades: list[Cidade] = field(default_factory=list)
    lotes: list[tuple[str, str, list[tuple[str, Metricas]]]] = field(default_factory=list)
    falhas: list[dict[str, Any]] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    def total_ideias(self) -> int:
        """Ideias distintas depois da uniao por termo normalizado."""
        return len({normalizar_termo(t) for _, _, itens in self.lotes for t, _ in itens})

    def __len__(self) -> int:
        # Vira o `target_count` do audit: o que a uniao devolve, nao o que o `limit` cortou.
        return self.total_ideias()


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
    req.language = comum.IDIOMA
    req.geo_target_constants.append(geo)
    req.keyword_plan_network = client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
    req.page_size = 1000
    if sementes is not None:
        req.keyword_seed.keywords.extend(sementes)
    else:
        req.url_seed.url = _com_esquema(url or "")
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
        res.cidades, res.avisos = comum.resolver_unicas(client, pedidos)
        alvos = comum.alvos(res.cidades)
        for origem, sementes, url in origens:
            for chave, geo in alvos:
                try:
                    itens = _ideias_da_origem(client, customer_id, geo, sementes=sementes, url=url)
                except GoogleAdsException as e:
                    friendly = to_friendly(e)
                    if sementes is not None or friendly.code in comum.CODIGOS_FATAIS:
                        raise
                    res.falhas.append({"origem": origem, "cidade": chave, "erro": str(friendly)})
                    continue
                res.lotes.append((origem, chave, itens))
        return res

    return chamadas


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
    concorrentes, avisos_urls = _concorrentes_unicos(site, list(args.get("concorrentes") or []))
    pedidos: list[str] = list(args.get("cidades") or [])
    limit = int(args.get("limit", 200))
    if not (sementes or site or concorrentes):
        return comum.erro(
            _OPERACAO, "Informe pelo menos um entre `sementes`, `site` e `concorrentes`."
        )

    origens: list[_Origem] = []
    if sementes:
        origens.append(("semente", sementes, None))
    if site:
        origens.append(("site", None, site))
    for url in concorrentes:
        origens.append((f"concorrente:{_dominio(url)}", None, url))

    # 2 por chamada de ideias: o SDK pagina (page_size=1000) e 2 sementes ja deram 2 paginas
    # (1.923 ideias), cada pagina um RPC.
    estimated_ops = (1 if pedidos else 0) + 2 * len(origens) * max(1, len(pedidos))
    try:
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
            resumo_do_resultado=lambda r: {
                "total_ideias": r.total_ideias(),
                "origens_com_falha": len(r.falhas),
            },
        )
    except GoogleAdsFriendlyError as e:
        if e.code != comum.CODIGO_CIDADE:
            raise
        return comum.erro(_OPERACAO, str(e))

    avisos = avisos_urls + comum.avisos_nome_difere(resultado.cidades) + resultado.avisos
    chaves = [chave for chave, _ in comum.alvos(resultado.cidades)]
    todas = unir(resultado.lotes)
    ideias, truncated = ordenar_e_cortar(todas, limit)
    return {
        "customer_id": customer_id,
        "recorte": {
            "cidades": comum.recorte_cidades(resultado.cidades),
            "idioma": comum.IDIOMA,
            "rede": comum.REDE,
        },
        "volume_em_degraus": True,
        "ideias": [
            {
                "termo": i.termo,
                "origens": i.origens,
                "volume_maximo": volume_maximo(i),
                # Toda cidade pedida aparece; a que nao devolveu a ideia vem com tudo `None`
                # (nao devolvida = sem dado, nunca zero), igual a get_keyword_metrics.
                "por_cidade": {c: i.por_cidade.get(c) or metricas_do_proto(None) for c in chaves},
            }
            for i in ideias
        ],
        "total_ideias": len(todas),
        "truncated": truncated,
        "origens_com_falha": resultado.falhas,
        "avisos": avisos,
    }
