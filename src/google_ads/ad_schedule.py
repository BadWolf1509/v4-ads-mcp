"""Dominio puro do ad_schedule (spec §4): janela, validacao, diff por conteudo, metricas.

Zero I/O. Tudo que sabe de fuso, GAQL ou SDK fica fora daqui.

Semantica de janela: cobre [start, end). `end_hour=24` com `end_minute=0`
significa "ate o fim do dia". Restricoes lidas do SDK v24 (`AdScheduleInfo`):
minutos so 0/15/30/45; dias MONDAY..SUNDAY.
"""

from __future__ import annotations

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
    )


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
    """
    atual_por_chave = {c.window.key(): c for c in current}
    desejada_por_chave = {w.key(): w for w in desired}
    to_add = tuple(w for k, w in desejada_por_chave.items() if k not in atual_por_chave)
    to_remove = tuple(c for k, c in atual_por_chave.items() if k not in desejada_por_chave)
    to_update: list[CurrentWindow] = []
    if bid_modifier is not None:
        for k, c in atual_por_chave.items():
            if k in desejada_por_chave and c.bid_modifier != bid_modifier:
                to_update.append(c)
    return ScheduleDiff(to_add=to_add, to_remove=to_remove, to_update=tuple(to_update))


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
    """
    return {cid: sorted(list(c.window.key()) for c in atual.get(cid, [])) for cid in campaign_ids}


def summarize_current(current: list[CurrentWindow]) -> dict[str, Any]:
    if not current:
        return {"has_schedule": False, "windows": 0, "hours_per_week": 168.0}
    return {
        "has_schedule": True,
        "windows": len(current),
        "hours_per_week": hours_per_week(c.window for c in current),
    }
