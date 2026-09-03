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
