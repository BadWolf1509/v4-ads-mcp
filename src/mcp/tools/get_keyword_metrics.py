# bucket: defer
"""Tool: get_keyword_metrics - metricas do Planejador para uma lista pronta de termos.

Uma chamada `generate_keyword_historical_metrics` por cidade (ou Brasil); o RPC nao
pagina. Termo sem dado volta SEM `keyword_metrics` (fato 6 do desenho): lido por
presenca, vira metricas `None`, nunca zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.google_ads.cidades import Cidade
from src.google_ads.errors import GoogleAdsFriendlyError
from src.google_ads.keyword_planning import run_keyword_planning
from src.google_ads.planejador import Metricas, metricas_do_proto, normalizar_termo
from src.mcp.context import get_current
from src.mcp.tools import _planejador_common as comum
from src.mcp.tools._registry import register_tool

_OPERACAO = "get_keyword_metrics"

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "termos": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "minItems": 1,
            "maxItems": 1000,
        },
        "cidades": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "maxItems": 5,
        },
    },
    "required": ["customer_id", "termos"],
    "additionalProperties": False,
}


@dataclass
class _Resultado:
    cidades: list[Cidade] = field(default_factory=list)
    # chave do recorte -> chave normalizada do termo -> (metricas, variantes)
    por_alvo: dict[str, dict[str, tuple[Metricas, list[str], bool]]] = field(default_factory=dict)
    chaves: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


def _metricas_do_alvo(
    client: Any, customer_id: str, geo: str, termos: list[str]
) -> dict[str, tuple[Metricas, list[str], bool]]:
    svc = client.get_service("KeywordPlanIdeaService")
    req = client.get_type("GenerateKeywordHistoricalMetricsRequest")
    req.customer_id = customer_id
    req.language = comum.IDIOMA
    req.geo_target_constants.append(geo)
    req.keyword_plan_network = client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
    req.keywords.extend(termos)
    resp = svc.generate_keyword_historical_metrics(request=req)
    saida: dict[str, tuple[Metricas, list[str], bool]] = {}
    for r in resp.results:
        tem = "keyword_metrics" in r
        m = r.keyword_metrics if tem else None
        saida.setdefault(
            normalizar_termo(r.text), (metricas_do_proto(m), list(r.close_variants), tem)
        )
    return saida


def _montar_chamadas(customer_id: str, pedidos: list[str], termos: list[str]) -> Any:
    def chamadas(client: Any) -> _Resultado:
        res = _Resultado()
        res.cidades, res.avisos = comum.resolver_unicas(client, pedidos)
        for chave, geo in comum.alvos(res.cidades):
            res.chaves.append(chave)
            res.por_alvo[chave] = _metricas_do_alvo(client, customer_id, geo, termos)
        return res

    return chamadas


def _sem_repeticao(termos: list[str]) -> list[str]:
    vistos: set[str] = set()
    saida: list[str] = []
    for t in termos:
        k = normalizar_termo(t)
        if k and k not in vistos:
            vistos.add(k)
            saida.append(t)
    return saida


@register_tool(
    name="get_keyword_metrics",
    description=(
        "[DEFER] Métricas do Planejador do Google para uma lista pronta de termos: volume "
        "mensal, concorrência, faixa de CPC e sazonalidade, por cidade. O volume vem em "
        "degraus do Google (10, 20, 50, 110...), não é exato; `null` significa que o Google "
        "não tem dado, não zero, e os termos sem dado em todas as cidades listam em "
        "`sem_dado`. O CPC é estimativa de topo de página, uma faixa (`cpc_topo_min_brl` a "
        "`cpc_topo_max_brl`), não o que a conta paga; os campos _brl assumem conta BRL. O "
        "resultado não depende da conta usada: use qualquer conta sua (ex.: a interna "
        "6728568947). Até 1000 termos, na ordem pedida; `variantes` ecoa as variantes "
        "próximas que o Google agrupa ao termo. Cidades por nome, com UF para desambiguar "
        "(ex.: 'João Pessoa, PB'), até 5; sem cidade o recorte é o Brasil. As métricas vêm por "
        "cidade em `por_cidade`, sem soma entre cidades."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def get_keyword_metrics(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id: str = args["customer_id"]
    termos = _sem_repeticao(list(args["termos"]))
    pedidos: list[str] = list(args.get("cidades") or [])
    if not termos:
        return comum.erro(_OPERACAO, "Informe pelo menos um termo não vazio em `termos`.")

    # Esse RPC nao pagina: 1 por cidade (ou Brasil), mais a resolucao de cidades.
    estimated_ops = (1 if pedidos else 0) + max(1, len(pedidos))
    try:
        resultado: _Resultado = await run_keyword_planning(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_name=_OPERACAO,
            estimated_ops=estimated_ops,
            params_summary={"termos": len(termos), "cidades": pedidos},
            chamadas=_montar_chamadas(customer_id, pedidos, termos),
        )
    except GoogleAdsFriendlyError as e:
        if e.code != comum.CODIGO_CIDADE:
            raise
        return comum.erro(_OPERACAO, str(e))

    saida: list[dict[str, Any]] = []
    sem_dado: list[str] = []
    for termo in termos:
        k = normalizar_termo(termo)
        por_cidade: dict[str, Metricas] = {}
        variantes: list[str] = []
        tem_dado = False
        for chave in resultado.chaves:
            achado = resultado.por_alvo[chave].get(k)
            metricas = achado[0] if achado else metricas_do_proto(None)
            por_cidade[chave] = metricas
            if achado:
                tem_dado = tem_dado or achado[2]
                variantes = variantes or achado[1]
        if not tem_dado:
            sem_dado.append(termo)
        saida.append({"termo": termo, "variantes": variantes, "por_cidade": por_cidade})

    return {
        "customer_id": customer_id,
        "recorte": {
            "cidades": comum.recorte_cidades(resultado.cidades),
            "idioma": comum.IDIOMA,
            "rede": comum.REDE,
        },
        "volume_em_degraus": True,
        "termos": saida,
        "sem_dado": sem_dado,
        "avisos": comum.avisos_nome_difere(resultado.cidades) + resultado.avisos,
    }
