"""`planejar_grade` (Task I1): o plano da grade como funcao pura, sem mock e sem I/O.

Os mesmos casos da caracterizacao (`test_update_ad_schedule_caracterizacao.py`),
agora chamando a funcao direto. A igualdade com o golden prova que mover o laco
para `ad_schedule.py` nao mudou um byte do preview nem das ops.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.google_ads.ad_schedule import (
    Window,
    _aviso_cobertura,
    _aviso_status,
    planejar_grade,
    rows_to_current,
    window_from_input,
)

_GOLDEN = json.loads(
    (Path(__file__).parent / "fixtures" / "grade_de_horario_caracterizacao.json").read_text(
        encoding="utf-8"
    )
)
_SEG = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY")


def _row(day: str, crit: str, bm: float | None = None) -> dict[str, Any]:
    return {
        "campaign_id": "1",
        "criterion_id": crit,
        "resource_name": f"customers/1234567890/campaignCriteria/1~{crit}",
        "day_of_week": day,
        "start_hour": 7,
        "start_minute": 0,
        "end_hour": 17,
        "end_minute": 0,
        "bid_modifier": bm,
    }


def _cel(day: str, hour: int, cost: float, conv: float) -> dict[str, Any]:
    return {
        "campaign_id": "1",
        "day_of_week": day,
        "hour": hour,
        "cost_micros": int(cost * 1_000_000),
        "conversions": conv,
    }


_METRICAS = [
    _cel("SATURDAY", 10, 100.0, 5.0),
    _cel("MONDAY", 8, 50.0, 2.0),
    _cel("MONDAY", 20, 30.0, 0.0),
]
_SEG_SEX = [window_from_input({"day_of_week": d, "start_hour": 7, "end_hour": 17}) for d in _SEG]
_MONDAY = window_from_input({"day_of_week": "MONDAY", "start_hour": 7, "end_hour": 17})


def _orc(shared: bool = False, status: str = "ENABLED") -> list[dict[str, Any]]:
    return [{"campaign_id": "1", "explicitly_shared": shared, "status": status}]


def _planejar(
    *,
    grade: list[dict[str, Any]],
    desejada: list[Window],
    bid_modifier: float | None = None,
    limpar: bool = False,
    orcamentos: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    orcamentos = orcamentos if orcamentos is not None else _orc()
    return planejar_grade(
        atual=rows_to_current(grade),
        desejada=desejada,
        bid_modifier=bid_modifier,
        campaign_ids=["1"],
        metricas=_METRICAS,
        limpar=limpar,
        status_da_campanha={o["campaign_id"]: o["status"] for o in orcamentos},
        orcamento_compartilhado=orcamentos,
    )


def test_24x7_para_faixas_so_adiciona() -> None:
    preview, ops = _planejar(grade=[], desejada=_SEG_SEX)
    assert preview == _GOLDEN["a"]["preview"]
    assert ops == _GOLDEN["a"]["ops"]
    assert {o["kind"] for o in ops} == {"add"}


def test_faixas_para_limpar_so_remove_e_cobertura_sobe_para_168() -> None:
    grade = [_row(d, str(i)) for i, d in enumerate(_SEG)]
    preview, ops = _planejar(grade=grade, desejada=[], limpar=True)
    assert preview == _GOLDEN["b"]["preview"]
    assert ops == _GOLDEN["b"]["ops"]
    assert {o["kind"] for o in ops} == {"remove"}
    assert preview["1"]["cobertura"]["horas_depois"] == 168.0
    assert preview["1"]["cobertura"]["reduz"] is False


def test_so_bid_modifier_faz_update_sem_recriar() -> None:
    preview, ops = _planejar(grade=[_row("MONDAY", "9", 1.3)], desejada=[_MONDAY], bid_modifier=0.8)
    assert preview == _GOLDEN["c"]["preview"]
    assert ops == _GOLDEN["c"]["ops"]
    assert ops == [
        {
            "kind": "update",
            "resource_name": "customers/1234567890/campaignCriteria/1~9",
            "bid_modifier": 0.8,
        }
    ]


def test_campanha_pausada_ganha_aviso_de_status() -> None:
    preview, ops = _planejar(grade=[], desejada=_SEG_SEX, orcamentos=_orc(status="PAUSED"))
    assert preview == _GOLDEN["d"]["preview"]
    assert ops == _GOLDEN["d"]["ops"]
    assert "PAUSED" in preview["1"]["aviso_status"]


def test_orcamento_compartilhado_com_cobertura_caindo_ganha_aviso() -> None:
    preview, ops = _planejar(grade=[], desejada=_SEG_SEX, orcamentos=_orc(shared=True))
    assert preview == _GOLDEN["e"]["preview"]
    assert ops == _GOLDEN["e"]["ops"]
    assert preview["1"]["aviso_cobertura"] is not None


def test_os_tres_formatos_de_op_no_mesmo_lote() -> None:
    grade = [_row("MONDAY", "1", 1.3), _row("TUESDAY", "2")]
    qua = window_from_input(
        {"day_of_week": "WEDNESDAY", "start_hour": 8, "end_hour": 12, "bid_modifier": 1.5}
    )
    preview, ops = _planejar(grade=grade, desejada=[_MONDAY, qua], bid_modifier=0.8)
    assert preview == _GOLDEN["f"]["preview"]
    assert ops == _GOLDEN["f"]["ops"]
    assert [o["kind"] for o in ops] == ["add", "remove", "update"]


def test_avisos_de_status_e_cobertura() -> None:
    assert _aviso_status("ENABLED") is None
    assert "PAUSED" in (_aviso_status("PAUSED") or "")
    assert "campanha SUSPENDED" in (_aviso_status("SUSPENDED") or "")
    assert _aviso_cobertura(True, True) is not None
    assert _aviso_cobertura(True, False) is None
    assert _aviso_cobertura(False, True) is None
