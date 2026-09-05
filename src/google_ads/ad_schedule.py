"""Dominio puro do ad_schedule (spec §4): janela, validacao, diff por conteudo, metricas.

Zero I/O. Tudo que sabe de fuso, GAQL ou SDK fica fora daqui.

Semantica de janela: cobre [start, end). `end_hour=24` com `end_minute=0`
significa "ate o fim do dia". Restricoes lidas do SDK v24 (`AdScheduleInfo`):
minutos so 0/15/30/45; dias MONDAY..SUNDAY.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

DIAS: tuple[str, ...] = (
    "MONDAY",
    "TUESDAY",
    "WEDNESDAY",
    "THURSDAY",
    "FRIDAY",
    "SATURDAY",
    "SUNDAY",
)
MINUTO_ENUM: dict[int, str] = {0: "ZERO", 15: "FIFTEEN", 30: "THIRTY", 45: "FORTY_FIVE"}
ENUM_MINUTO: dict[str, int] = {v: k for k, v in MINUTO_ENUM.items()} | {
    "UNSPECIFIED": 0,
    "UNKNOWN": 0,
}


@dataclass(frozen=True, slots=True)
class Window:
    day_of_week: str
    start_hour: int
    start_minute: int
    end_hour: int
    end_minute: int
    # F149: ATRIBUTO, nao identidade. `key()` deliberadamente nao o inclui —
    # ver o teste que cobra isso e o custo de recriar criterion.
    bid_modifier: float | None = None

    def key(self) -> tuple[str, int, int, int, int]:
        return (
            self.day_of_week,
            self.start_hour,
            self.start_minute,
            self.end_hour,
            self.end_minute,
        )

    def start_min(self) -> int:
        return self.start_hour * 60 + self.start_minute

    def end_min(self) -> int:
        return self.end_hour * 60 + self.end_minute


def window_from_input(d: dict[str, Any]) -> Window:
    return Window(
        day_of_week=str(d["day_of_week"]),
        start_hour=int(d["start_hour"]),
        start_minute=int(d.get("start_minute", 0)),
        end_hour=int(d["end_hour"]),
        end_minute=int(d.get("end_minute", 0)),
        bid_modifier=(float(d["bid_modifier"]) if d.get("bid_modifier") is not None else None),
    )


_UTEIS = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY")

# 50h + 70h + 48h = 168h. O teste cobra essa soma: bloco que nao ladrilha
# transforma `outros` em lixeira e a comparacao entre blocos vira ruido.
BLOCOS_PADRAO: dict[str, list[Window]] = {
    "comercial": [Window(d, 8, 0, 18, 0) for d in _UTEIS],
    "fora_de_hora": [Window(d, 0, 0, 8, 0) for d in _UTEIS]
    + [Window(d, 18, 0, 24, 0) for d in _UTEIS],
    "fim_de_semana": [Window("SATURDAY", 0, 0, 24, 0), Window("SUNDAY", 0, 0, 24, 0)],
}


def validate_windows(windows: list[dict[str, Any]]) -> str | None:
    """Mensagem PT-BR se algo for invalido; None se OK. Recusa ANTES do Google."""
    validos = ", ".join(str(m) for m in MINUTO_ENUM)
    parsed: list[Window] = []
    for i, d in enumerate(windows):
        try:
            w = window_from_input(d)
        except (KeyError, ValueError, TypeError) as e:
            return f"windows[{i}]: janela malformada — precisa de day_of_week, start_hour e end_hour inteiros ({e.__class__.__name__}: {e})"
        if w.day_of_week not in DIAS:
            return (
                f"windows[{i}]: day_of_week '{w.day_of_week}' invalido; use um de {', '.join(DIAS)}"
            )
        for nome, m in (("start_minute", w.start_minute), ("end_minute", w.end_minute)):
            if m not in MINUTO_ENUM:
                return (
                    f"windows[{i}]: {nome}={m} nao existe na API do Google Ads — "
                    f"minutos validos: {validos} (nao e possivel agendar 07:10)"
                )
        if not (0 <= w.start_hour <= 23):
            return f"windows[{i}]: start_hour={w.start_hour} fora de 0..23"
        if not (0 <= w.end_hour <= 24) or (w.end_hour == 24 and w.end_minute != 0):
            return f"windows[{i}]: end_hour deve estar em 0..24 (24 so com end_minute=0)"
        if w.end_min() <= w.start_min():
            return f"windows[{i}]: fim ({w.end_hour:02d}:{w.end_minute:02d}) tem que ser depois do inicio"
        parsed.append(w)
    por_dia: dict[str, list[Window]] = {}
    for w in parsed:
        por_dia.setdefault(w.day_of_week, []).append(w)
    for dia, ws in por_dia.items():
        ws_sorted = sorted(ws, key=lambda x: x.start_min())
        for a, b in zip(ws_sorted, ws_sorted[1:], strict=False):
            if b.start_min() < a.end_min():
                return f"janelas sobrepostas em {dia}: {a.start_hour:02d}:{a.start_minute:02d}-{a.end_hour:02d}:{a.end_minute:02d} e {b.start_hour:02d}:{b.start_minute:02d}-{b.end_hour:02d}:{b.end_minute:02d}"
    return None


def hours_per_week(windows: Iterable[Window]) -> float:
    return round(sum((w.end_min() - w.start_min()) / 60 for w in windows), 2)


@dataclass(frozen=True, slots=True)
class CurrentWindow:
    window: Window
    resource_name: str
    criterion_id: str
    bid_modifier: float | None


@dataclass(frozen=True, slots=True)
class ScheduleDiff:
    to_add: tuple[Window, ...]
    to_remove: tuple[CurrentWindow, ...]
    to_update: tuple[CurrentWindow, ...]

    def is_empty(self) -> bool:
        return not (self.to_add or self.to_remove or self.to_update)

    def op_count(self) -> int:
        return len(self.to_add) + len(self.to_remove) + len(self.to_update)


def diff_schedule(
    current: list[CurrentWindow], desired: list[Window], bid_modifier: float | None
) -> ScheduleDiff:
    """Grade desejada e CONJUNTO (spec §4.1); diff por CONTEUDO (§4.4).

    - janela desejada ausente do atual -> add
    - janela atual ausente da desejada -> remove
    - janela em ambos com bid_modifier informado e diferente -> update (mask), nunca recria

    F149: cada janela pode trazer seu proprio modificador; o escalar so e default.
    """
    atual_por_chave = {c.window.key(): c for c in current}
    desejada_por_chave = {w.key(): w for w in desired}
    to_add = tuple(w for k, w in desejada_por_chave.items() if k not in atual_por_chave)
    to_remove = tuple(c for k, c in atual_por_chave.items() if k not in desejada_por_chave)
    to_update: list[CurrentWindow] = []
    for k, c in atual_por_chave.items():
        desejada = desejada_por_chave.get(k)
        if desejada is None:
            continue
        # F149: o modificador da JANELA vence; o escalar da chamada e o default
        # de quem nao trouxe o seu. Ambos ausentes = preserva (comportamento de hoje).
        efetivo = modificador_efetivo(desejada, bid_modifier)
        # Fix C1 (revisao final): comparar por `!=` compara o float64 que o gestor
        # pediu com o float32 (proto.FLOAT, SDK v24) que o Google devolve — 1.4
        # volta 1.399999976158142, e a feature nunca convergia (T4/T5 do runbook
        # 3b.44 falhavam: reenviar a MESMA grade emitia update e mintava token).
        # `bid_modifier_diverge` absorve o arredondamento com tolerancia.
        if efetivo is not None and bid_modifier_diverge(c.bid_modifier, efetivo):
            to_update.append(c)
    return ScheduleDiff(to_add=to_add, to_remove=to_remove, to_update=tuple(to_update))


def modificador_efetivo(janela: Window, escalar: float | None) -> float | None:
    """F149: o modificador da JANELA vence; o escalar da chamada e o default de
    quem nao trouxe o seu; ambos ausentes preserva o valor atual (None).

    Mesma regra que `diff_schedule` aplica em `to_update` via esta chamada.
    Este helper centraliza a regra pra evitar a familia do F81: cada lado certo
    sozinho e o conjunto errado junto. Usada em 5 call-sites (conferido por
    grep, nao de memoria — foi assim que o numero anterior, "4", errou):
    `diff_schedule` + 4 na tool (`windows_added` do preview, `bid_modifier_novo`
    do preview, op `add`, op `update`).
    """
    return janela.bid_modifier if janela.bid_modifier is not None else escalar


def bid_modifier_diverge(atual: float | None, esperado: float) -> bool:
    """Fix C1 (revisao final): True se o ATUAL (lido do Google) diverge do
    ESPERADO (pedido pelo gestor OU efetivo calculado por `modificador_efetivo`).

    O SDK v24 declara `bid_modifier` como `proto.FLOAT` — 32 bits. O gestor
    grava 1.4 (float64 exato) e o Google devolve 1.399999976158142 na proxima
    leitura. Comparar por `==` nunca converge: toda chamada repetida veria
    diferenca onde nao ha — media contra o dominio real, T4 do runbook 3b.44
    (reenviar a MESMA grade) e T5 (janela com valor igual ao atual) falhavam.

    `math.isclose(rel_tol=1e-6)` absorve o erro de arredondamento do float32
    (~1e-7) sem mascarar mudanca de verdade: a granularidade real que o Google
    aceita e 0.01, ordens de grandeza acima do rel_tol escolhido. `atual is
    None` sempre diverge (nao ha "None isclose float" — `math.isclose` nao
    aceita `None`, e semanticamente "nunca teve modificador" e sempre diferente
    de um valor pedido).

    Usada em dois call-sites com a MESMA tolerancia — `diff_schedule` (decidir
    `to_update`) e `apply_change` (confirmar `matches_requested` contra o que
    foi de fato pedido por janela) — pra nao repetir a familia do F81. NAO use
    isto em `schedule_fingerprint`: as duas pontas la leem do Google pelo MESMO
    parser, entao igualdade exata e correta e MAIS estrita, e o round-trip
    JSONB preserva os bits (comparar com tolerancia ali esconderia divergencia
    real entre preview e apply).
    """
    if atual is None:
        return True
    return not math.isclose(atual, esperado, rel_tol=1e-6)


@dataclass(frozen=True, slots=True)
class MetricCell:
    day_of_week: str
    hour: int
    cost_micros: int
    conversions: float


METRICS_GRANULARITY = "hora cheia; janelas com minutos sao aproximadas a hora cheia"


def covers(windows: list[Window] | None, day_of_week: str, hour: int) -> bool:
    """`None` = campanha sem AD_SCHEDULE = serve 24x7. Celula (dia, h) coberta se h:00 esta em [start, end)."""
    if windows is None:
        return True
    instante = hour * 60
    return any(
        w.day_of_week == day_of_week and w.start_min() <= instante < w.end_min() for w in windows
    )


def _agrega(cells: list[MetricCell]) -> dict[str, Any]:
    cost = sum(c.cost_micros for c in cells)
    conv = sum(c.conversions for c in cells)
    cost_brl = round(cost / 1_000_000, 2)
    return {
        "cost_brl": cost_brl,
        "conversions": round(conv, 2),
        "cpa_brl": round(cost_brl / conv, 2) if conv > 0 else None,
        "cells": len(cells),
    }


def partition_metrics(
    cells: list[MetricCell], before: list[Window] | None, after: list[Window]
) -> dict[str, Any]:
    """Spec §4.2: o preview responde 'o que estou desligando e melhor ou pior do que fica?'."""
    leaving = [
        c
        for c in cells
        if covers(before, c.day_of_week, c.hour) and not covers(after, c.day_of_week, c.hour)
    ]
    staying = [c for c in cells if covers(after, c.day_of_week, c.hour)]
    return {
        "leaving": _agrega(leaving),
        "staying": _agrega(staying),
        "metrics_granularity": METRICS_GRANULARITY,
    }


def schedule_fingerprint(
    atual: dict[str, list[CurrentWindow]], campaign_ids: list[str]
) -> dict[str, list[list[Any]]]:
    """Impressao do baseline observado, por campanha — comparavel apos ida e volta por JSON.

    Ruling 10 (concorrencia otimista): o dry-run guarda isto no token e o apply
    recomputa antes de mutar. Listas, nunca tuplas: o payload atravessa JSONB, e
    tupla volta lista — comparar tupla com lista daria divergencia em TODO apply.
    Campanha sem janela entra como `[]`, para "sem grade" nao se confundir com
    "campanha ausente do fingerprint" (familia do F131).

    As duas pontas chamam ESTA funcao: fingerprint calculado de dois jeitos
    diferentes e a classe do F81 — cada lado certo sozinho, o par errado.

    Agora inclui o bid_modifier como a 6a posicao para fechar a concorrencia otimista:
    Ruling 1 do scan: NUNCA comparar a 6a posicao diretamente — ela pode ser None
    num registro e float noutro, e `sorted` estouraria com TypeError. O `key=`
    abaixo e defesa contra um estado que este scan NAO PROVOU alcancavel — duas
    criterias com a MESMA faixa e modificadores diferentes — nao afirmacao de
    que ele exista: o SDK v24 traz `CriterionError.AD_SCHEDULE_TIME_INTERVALS_
    OVERLAP` (=56) e o Google RECUSA janelas sobrepostas (Fix M5/revisao final
    da branch — a premissa anterior, "existem se criadas pela UI ou por outra
    API", nao tinha probe e o enum a contradiz). Mantida porque a defesa e
    barata e o fingerprint le o ATUAL do Google, nao a entrada validada.
    """
    return {
        cid: sorted(
            ([*c.window.key(), c.bid_modifier] for c in atual.get(cid, [])),
            key=lambda linha: (linha[:5], linha[5] is None, linha[5] or 0.0),
        )
        for cid in campaign_ids
    }


def partition_by_blocks(
    cells: list[MetricCell], blocos: dict[str, list[Window]]
) -> dict[str, dict[str, Any]]:
    """Particiona celulas dia x hora em blocos nomeados. TOTAL por construcao.

    Toda celula cai em exatamente um balde: o primeiro bloco que a cobre, ou
    `outros`. Sem isso a soma dos blocos nao bate com o total da conta, e o
    gestor compara CPA de blocos que juntos nao explicam o gasto.
    """
    baldes: dict[str, list[MetricCell]] = {nome: [] for nome in blocos}
    baldes["outros"] = []
    for c in cells:
        destino = next(
            (nome for nome, janelas in blocos.items() if covers(janelas, c.day_of_week, c.hour)),
            "outros",
        )
        baldes[destino].append(c)
    return {nome: _agrega(cs) for nome, cs in baldes.items()}


def summarize_current(current: list[CurrentWindow]) -> dict[str, Any]:
    if not current:
        return {"has_schedule": False, "windows": 0, "hours_per_week": 168.0}
    return {
        "has_schedule": True,
        "windows": len(current),
        "hours_per_week": hours_per_week(c.window for c in current),
    }
