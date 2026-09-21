"""F188: a conjunta dia x hora precisa de ordem, porque alguém fatia o resultado dela.

`get_performance_breakdown(raw_grid=true)` devolve `celulas[:teto]` — fatia de uma lista
que vem do Google **sem `ORDER BY`**. Medido em 2026-09-20: duas chamadas idênticas
diferindo só no `limit` devolveram as MESMAS 213 células em ordens diferentes, e nenhuma
das duas truncou. Logo a diferença não veio do corte; veio da ordem do Google, que não é
estável.

Custa duas coisas: ordem não reprodutível (quem usa `raw_grid` confere célula a célula e
não consegue diffar duas execuções) e, quando trunca, **amostra arbitrária apresentada
como grade** — `truncated: true` diz que cortou, não diz o quê.

## Por que este guard é ESTREITO, e por que isso não é preguiça

A invariante tentadora seria "toda query GAQL tem `ORDER BY`". **Medi antes de escrever:
27 funções montam GAQL neste repo e 24 não ordenam** — e na maioria isso está CERTO, são
pré-flights que buscam entidade por id, onde o chamador indexa por id e ordem não
significa nada. Um guard de classe exigiria 24 isenções, que é ruído com aparência de
rigor.

A invariante real é sobre o **corte**, não sobre a query: *lista que alguém fatia precisa
de ordem determinística*. Ligar corte a query exige análise de fluxo de dados que eu não
vou fingir que fiz.

**O que fica FORA, dito para não ser confundido com cobertura:** os outros cortes
client-side de `src/mcp/tools/` (`rows[:limit]` em budget_pacing, conversion_actions,
recommendations, run_gaql, e as amostras de preview `[:3]`). Vários vêm de queries que
ordenam por custo desc, mas **isto aqui não verifica nenhum deles.**

## E por que asserir os TRÊS campos

`ORDER BY campaign.id` sozinho passaria numa checagem de presença e **não resolveria
nada**: as células de uma mesma campanha continuariam sem ordem entre si. A ordem só fica
determinística com as três dimensões da grade — campanha, dia, hora.
"""

from __future__ import annotations

from src.google_ads.queries.ad_schedule import day_hour_metrics_query

_CAMPOS = ("campaign.id", "segments.day_of_week", "segments.hour")


def _query() -> str:
    from datetime import date

    return day_hour_metrics_query(
        campaign_ids=["111", "222"], start=date(2026, 8, 1), end=date(2026, 8, 31)
    )


def test_a_conjunta_dia_hora_tem_order_by() -> None:
    q = _query()
    assert "ORDER BY" in q.upper(), (
        "`day_hour_metrics_query` não tem `ORDER BY`, e o `raw_grid` do "
        "`get_performance_breakdown` fatia o resultado dela (`celulas[:teto]`). Fatia de "
        "lista sem ordem é amostra arbitrária apresentada como grade (F188)."
    )


def test_a_ordem_cobre_as_tres_dimensoes_da_grade() -> None:
    """Presença de `ORDER BY` não basta — tem de ordenar campanha, dia E hora.

    Com só `campaign.id`, as células de uma mesma campanha seguem sem ordem entre si e o
    defeito continua, agora com um guard verde por cima. É o modo 7 do caderno: asserir o
    ADJACENTE à invariante.
    """
    q = _query().upper()
    trecho = q[q.index("ORDER BY") :] if "ORDER BY" in q else ""
    faltando = [c for c in _CAMPOS if c.upper() not in trecho]
    assert not faltando, (
        "o `ORDER BY` da conjunta não cobre "
        + ", ".join(faltando)
        + ". A grade tem três dimensões (campanha, dia, hora); ordenar por um subconjunto "
        "deixa o resto arbitrário e o F188 de pé."
    )


def test_a_ordem_das_chaves_vai_do_maior_pro_menor_agrupamento() -> None:
    """`campaign.id` antes de `day_of_week` antes de `hour`.

    Não é estética: o consumidor do `raw_grid` lê a grade de uma campanha por vez, e o
    corte `celulas[:teto]`, quando dispara, passa a ser um prefixo COMPLETO das primeiras
    campanhas em vez de um pedaço de todas — degradação muito mais legível.
    """
    q = _query().upper()
    assert "ORDER BY" in q, (
        "sem `ORDER BY` não há ordem de chaves para conferir — o teste irmão explica. "
        "Esta asserção existe para o vermelho sair como mensagem e não como ValueError."
    )
    trecho = q[q.index("ORDER BY") :]
    faltando = [c for c in _CAMPOS if c.upper() not in trecho]
    assert not faltando, f"campos ausentes do `ORDER BY`: {faltando} — ver teste irmão."
    posicoes = [trecho.index(c.upper()) for c in _CAMPOS]
    assert posicoes == sorted(posicoes), (
        f"ordem das chaves do `ORDER BY` fora do esperado {_CAMPOS}: as posições "
        f"vieram {posicoes}. Do agrupamento maior para o menor, senão o corte fatia "
        "todas as campanhas pela metade em vez de completar as primeiras."
    )
