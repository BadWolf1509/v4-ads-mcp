"""Planejador de palavras-chave: leitura das metricas e uniao das ideias (puro).

Sem I/O e sem importar cliente/servico do Google: recebe as mensagens ja lidas.
Regra "nao medido nao e zero": campo que nao veio no proto e `None`, lido por
presenca (`"campo" in msg`) — ler o atributo direto devolveria `0`.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, TypedDict

from src.google_ads.queries._common import arredondado, micros_to_currency, razao


class Metricas(TypedDict):
    volume_mensal: int | None
    concorrencia: str | None
    indice_concorrencia: int | None
    cpc_topo_min_brl: float | None
    cpc_topo_max_brl: float | None
    sazonalidade: dict[str, Any] | None


# Niveis que o Google devolve quando nao mediu a concorrencia.
_CONCORRENCIA_NAO_MEDIDA = frozenset({"UNSPECIFIED", "UNKNOWN"})


def _vazias() -> Metricas:
    return {
        "volume_mensal": None,
        "concorrencia": None,
        "indice_concorrencia": None,
        "cpc_topo_min_brl": None,
        "cpc_topo_max_brl": None,
        "sazonalidade": None,
    }


def _mes_numero(mes: Any) -> int:
    # Enum MonthOfYear do Google: UNSPECIFIED=0, UNKNOWN=1, JANUARY=2 ... DECEMBER=13.
    return int(mes) - 1


def sazonalidade(meses: Sequence[Any]) -> dict[str, Any] | None:
    """Pico, vale e variacao do primeiro ao ultimo mes; `None` com menos de 12 meses."""
    if len(meses) < 12:
        return None
    ordenados = sorted(meses, key=lambda x: (x.year, _mes_numero(x.month)))

    def rotulo(x: Any) -> str:
        return f"{x.year:04d}-{_mes_numero(x.month):02d}"

    # `max`/`min` devolvem o primeiro empatado; varrer ao contrario fica com o mais recente.
    recentes_primeiro = list(reversed(ordenados))
    pico = max(recentes_primeiro, key=lambda x: x.monthly_searches)
    vale = min(recentes_primeiro, key=lambda x: x.monthly_searches)
    primeiro, ultimo = ordenados[0].monthly_searches, ordenados[-1].monthly_searches
    variacao = arredondado(razao(ultimo - primeiro, primeiro), 3)
    return {
        "mes_pico": rotulo(pico),
        "mes_vale": rotulo(vale),
        "variacao_12m_pct": None if variacao is None else round(variacao * 100, 1),
    }


def metricas_do_proto(m: Any | None) -> Metricas:
    """`KeywordPlanHistoricalMetrics` -> `Metricas`; cada campo so existe se veio."""
    r = _vazias()
    if m is None:
        return r
    if "avg_monthly_searches" in m:
        r["volume_mensal"] = int(m.avg_monthly_searches)
    if "competition" in m and m.competition.name not in _CONCORRENCIA_NAO_MEDIDA:
        r["concorrencia"] = m.competition.name
    if "competition_index" in m:
        r["indice_concorrencia"] = int(m.competition_index)
    if "low_top_of_page_bid_micros" in m:
        r["cpc_topo_min_brl"] = micros_to_currency(m.low_top_of_page_bid_micros)
    if "high_top_of_page_bid_micros" in m:
        r["cpc_topo_max_brl"] = micros_to_currency(m.high_top_of_page_bid_micros)
    if len(m.monthly_search_volumes):
        r["sazonalidade"] = sazonalidade(list(m.monthly_search_volumes))
    return r


def normalizar_termo(t: str) -> str:
    """Minusculas, sem acento (NFKD) e espacos colapsados: chave de uniao."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c)
    )
    return " ".join(sem_acento.lower().split())


@dataclass
class Ideia:
    termo: str
    origens: list[str] = field(default_factory=list)
    por_cidade: dict[str, Metricas] = field(default_factory=dict)


def unir(
    lotes: Iterable[tuple[str, str, Iterable[tuple[str, Metricas]]]],
) -> list[Ideia]:
    """Une os lotes `(origem, cidade, [(termo, metricas)])` por termo normalizado.

    O primeiro texto visto fica; origens sem repeticao na ordem de aparicao; a
    primeira metrica vista por cidade vence. Nao soma cidades: volume de cidades
    sobrepostas (capital e regiao metropolitana) contaria a mesma busca duas vezes.
    """
    por_chave: dict[str, Ideia] = {}
    for origem, cidade, itens in lotes:
        for termo, metricas in itens:
            ideia = por_chave.setdefault(normalizar_termo(termo), Ideia(termo=termo))
            if origem not in ideia.origens:
                ideia.origens.append(origem)
            ideia.por_cidade.setdefault(cidade, metricas)
    return list(por_chave.values())


def volume_maximo(i: Ideia) -> int | None:
    """Maior volume entre as cidades, ignorando as nao medidas."""
    volumes = [v for m in i.por_cidade.values() if (v := m["volume_mensal"]) is not None]
    return max(volumes) if volumes else None


def ordenar_e_cortar(ideias: list[Ideia], limit: int) -> tuple[list[Ideia], bool]:
    """Volume maximo desc, `None` por ultimo, desempate por termo; `(cortada, truncated)`."""

    def chave(i: Ideia) -> tuple[int, int, str]:
        v = volume_maximo(i)
        return (1, 0, i.termo) if v is None else (0, -v, i.termo)

    ordenadas = sorted(ideias, key=chave)
    return ordenadas[:limit], len(ordenadas) > limit
