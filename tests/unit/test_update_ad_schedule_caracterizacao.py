"""Caracterizacao de `update_ad_schedule`: `preview` e `payload["ops"]` por IGUALDADE TOTAL.

Escrito ANTES de mover o laco de planejamento para `planejar_grade` (Task I1) e
verde contra o codigo anterior: pina o contrato byte a byte, nao por substring.
O golden vive em `fixtures/grade_de_horario_caracterizacao.json` e foi gerado
chamando a tool com os fakes de `test_update_ad_schedule.py`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.mcp.tools import update_ad_schedule as mod
from tests.unit.test_update_ad_schedule import (
    SEG_SEX,
    _cell,
    _ctx,  # noqa: F401  (fixture autouse)
    _janela_row,
    _orc,
    _wire,
)

_GOLDEN = json.loads(
    (Path(__file__).parent / "fixtures" / "grade_de_horario_caracterizacao.json").read_text(
        encoding="utf-8"
    )
)
_SEG = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY")
_CELULAS = [
    _cell(day="SATURDAY", hour=10, cost=100.0, conv=5.0),
    _cell(day="MONDAY", hour=8, cost=50.0, conv=2.0),
    _cell(day="MONDAY", hour=20, cost=30.0, conv=0.0),
]
_MONDAY = {"day_of_week": "MONDAY", "start_hour": 7, "end_hour": 17}

_CASOS: dict[str, dict[str, Any]] = {
    # 24x7 -> faixas: so `add`
    "a": {"grade": [], "orc": [_orc()], "args": {"windows": SEG_SEX}},
    # faixas -> limpar: so `remove`
    "b": {
        "grade": [_janela_row(day=d, crit=str(i)) for i, d in enumerate(_SEG)],
        "orc": [_orc()],
        "args": {"clear_schedule": True},
    },
    # so bid_modifier: so `update`
    "c": {
        "grade": [_janela_row(day="MONDAY", bm=1.3)],
        "orc": [_orc()],
        "args": {"windows": [_MONDAY], "bid_modifier": 0.8},
    },
    # campanha pausada: aviso_status
    "d": {"grade": [], "orc": [_orc(status="PAUSED")], "args": {"windows": SEG_SEX}},
    # orcamento compartilhado + cobertura cai: aviso_cobertura
    "e": {"grade": [], "orc": [_orc(shared=True)], "args": {"windows": SEG_SEX}},
    # os tres formatos de op no mesmo lote
    "f": {
        "grade": [
            _janela_row(day="MONDAY", crit="1", bm=1.3),
            _janela_row(day="TUESDAY", crit="2"),
        ],
        "orc": [_orc()],
        "args": {
            "windows": [
                _MONDAY,
                {"day_of_week": "WEDNESDAY", "start_hour": 8, "end_hour": 12, "bid_modifier": 1.5},
            ],
            "bid_modifier": 0.8,
        },
    },
}


@pytest.mark.asyncio
@pytest.mark.parametrize("caso", sorted(_CASOS))
async def test_preview_e_ops_batem_com_o_golden(monkeypatch, caso: str) -> None:
    c = _CASOS[caso]
    captured = _wire(monkeypatch, grade=c["grade"], orcamentos=c["orc"], metricas=_CELULAS)
    out = await mod.update_ad_schedule(
        {"customer_id": "1234567890", "campaign_ids": ["1"], **c["args"]}
    )
    assert out["status"] == "dry_run"
    assert out["preview"] == _GOLDEN[caso]["preview"]
    assert captured["payload"]["ops"] == _GOLDEN[caso]["ops"]


def test_golden_cobre_os_tres_formatos_de_op() -> None:
    assert {o["kind"] for o in _GOLDEN["f"]["ops"]} == {"add", "remove", "update"}
