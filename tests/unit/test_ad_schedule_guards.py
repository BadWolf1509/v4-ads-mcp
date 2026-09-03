"""Guards do ad_schedule que nao cabem nos testes de comportamento.

Regra do repo: guard que assere o ADJACENTE nao e guard. Aqui se assere
propriedade (assinatura, conjunto), nao presenca de string.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from src.google_ads.ad_schedule import diff_schedule, partition_metrics, validate_windows


def test_diff_recebe_grade_completa_e_bid_modifier_explicito() -> None:
    p = inspect.signature(diff_schedule).parameters
    assert list(p) == ["current", "desired", "bid_modifier"]
    assert p["bid_modifier"].default is inspect.Parameter.empty, "sem default: o chamador decide"


def test_partition_metrics_exige_before_e_after() -> None:
    p = inspect.signature(partition_metrics).parameters
    assert list(p) == ["cells", "before", "after"] and all(
        x.default is inspect.Parameter.empty for x in p.values()
    )


def test_validate_windows_menciona_os_quatro_minutos_validos() -> None:
    err = validate_windows(
        [{"day_of_week": "MONDAY", "start_hour": 7, "start_minute": 10, "end_hour": 17}]
    )
    assert err is not None and all(m in err for m in ("0", "15", "30", "45"))


def _chamadas(src: str, nome: str) -> int:
    return sum(
        1
        for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == nome
    )


def test_update_ad_schedule_usa_envelope_e_classify_do_compartilhado() -> None:
    """Spec §8.10 (espirito do F112): nem envelope a mao, nem nivel fixado sem classify."""
    src = Path("src/mcp/tools/update_ad_schedule.py").read_text(encoding="utf-8")
    assert _chamadas(src, "classify") >= 1
    assert _chamadas(src, "preview_envelope") >= 1 and _chamadas(src, "error_envelope") >= 1
    assert "DEFAULT_TTL_MINUTES" not in src and "expires_in_minutes" not in src, (
        "TTL vem do envelope, nao da tool"
    )
