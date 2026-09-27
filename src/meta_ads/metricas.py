"""O contrato das métricas Meta — a ÚNICA leitura de métrica de uma linha da Graph API.

Spec 2026-09-26 (métricas Meta dizem o que mediram). Antes deste módulo, os mesmos
campos saíam por duas regras: `insights.py` (trio e breakdown) buscava o nome exato
`purchase`, que nenhuma das 24 contas medidas devolve, e reportava `purchases: 0`
sobre 10 compras reais; `account_overview.py` somava seis nomes, o que conta o mesmo
evento várias vezes quando a conta devolve recortes sobrepostos. O `ctr` saía em
fração num e em porcentagem no outro. É o F189/F190 de novo — a regra consertada num
gêmeo e não no outro —, e por isso o guard estrutural (`test_meta_metricas_guards.py`)
proíbe qualquer outro arquivo Meta de ler chave de métrica da linha.

Três regras, uma fonte:

1. **Um nome por campo, nunca soma de nomes.** Medido em 26/09: a mesma compra sai
   sob 5 nomes e o mesmo lead sob 7; somar recortes multiplica o evento.
2. **Ausente é `None`.** A Meta OMITE o tipo de ação com zero ocorrência, então
   `None` quer dizer "não reportado: zero ou não rastreado — a API não distingue".
   Valor que não converte para número também é `None`. Zero só quando a Meta manda
   zero.
3. **`ctr` em fração**, como o `ctr` do Google: a Meta manda porcentagem.

Puro: sem IO, sem SDK.
"""

import math
from typing import Any

# O mapa canônico (spec §3.1). Os totais que o Gerenciador de Anúncios chama de
# "Compras" e "Leads"; os outros nomes medidos são recortes do mesmo número.
ACAO_COMPRA = "omni_purchase"
ACAO_LEAD = "lead"
ACAO_CONVERSA = "onsite_conversion.messaging_conversation_started_7d"

# Toda chamada /insights sai com `use_unified_attribution_setting=true`
# (`insights.build_insights_call`), e a resposta diz qual atribuição usou.
ATRIBUICAO = "unificada"

# Frases que as descriptions das tools Meta de métrica carregam — uma fonte só, e o
# teste de description confere a presença por varredura do registry.
FRASE_DO_NULL = "Metrica null = a Meta nao reportou: zero ou nao rastreado (a API nao distingue)."
FRASE_DO_CTR = "ctr em fracao (0.0283 = 2,83%), como no Google."
FRASE_DA_ATRIBUICAO = "Atribuicao unificada: a do conjunto de anuncios, como no Gerenciador."
CONTRATO_NA_DESCRIPTION = f"{FRASE_DO_NULL} {FRASE_DO_CTR} {FRASE_DA_ATRIBUICAO}"

MetricaMeta = float | int | None


def _numero(valor: Any) -> float | None:
    if valor is None:
        return None
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    # "nan" e "inf" convertem em float e derrubavam o round() da contagem — a
    # resposta inteira caia. Numero nao finito e valor que nao converte: null.
    return numero if math.isfinite(numero) else None


def _contagem(valor: float | None) -> int | None:
    """Arredonda, não trunca: `int(2.9)` dava 2."""
    return None if valor is None else round(valor)


def _casas(valor: float | None, casas: int) -> float | None:
    return None if valor is None else round(valor, casas)


def _da_acao(lista: Any, tipo: str) -> float | None:
    """Valor do tipo `tipo` numa lista de ações Graph. Tipo ausente -> `None`."""
    if not isinstance(lista, list):
        return None
    for item in lista:
        if isinstance(item, dict) and item.get("action_type") == tipo:
            return _numero(item.get("value"))
    return None


def metricas_da_linha(linha: dict[str, Any]) -> dict[str, MetricaMeta]:
    """As métricas de UMA linha /insights, pelo contrato. Os nomes são os da resposta."""
    ctr = _numero(linha.get("ctr"))
    return {
        "spend_brl": _casas(_numero(linha.get("spend")), 2),
        "impressions": _contagem(_numero(linha.get("impressions"))),
        "clicks": _contagem(_numero(linha.get("clicks"))),
        "ctr": None if ctr is None else round(ctr / 100, 4),
        "cpc_brl": _casas(_numero(linha.get("cpc")), 4),
        "reach": _contagem(_numero(linha.get("reach"))),
        "frequency": _casas(_numero(linha.get("frequency")), 2),
        "purchases": _contagem(_da_acao(linha.get("actions"), ACAO_COMPRA)),
        "purchases_value_brl": _casas(_da_acao(linha.get("action_values"), ACAO_COMPRA), 2),
        "purchase_roas": _casas(_da_acao(linha.get("purchase_roas"), ACAO_COMPRA), 2),
        "leads": _contagem(_da_acao(linha.get("actions"), ACAO_LEAD)),
        "messaging_conversations_started": _contagem(_da_acao(linha.get("actions"), ACAO_CONVERSA)),
    }


def metricas_sem_linha() -> dict[str, MetricaMeta]:
    """Período em que a Meta não devolveu linha nenhuma (spec §3.4).

    A Meta não manda linha zerada — sem entrega, não vem linha. Entrega em 0 é
    verdade (não houve impressão, clique, gasto nem alcance); eventos, valores e
    razões ficam `None`, pela regra 2: a Meta não diz se a conta rastreia o evento.
    Derivado de `metricas_da_linha({})`, então as chaves não divergem.
    """
    return {
        **metricas_da_linha({}),
        "spend_brl": 0.0,
        "impressions": 0,
        "clicks": 0,
        "reach": 0,
    }
