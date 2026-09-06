"""Testes do próprio harness.

Um harness de guards com bug é o mesmo defeito um nível acima: todo guard
construído sobre ele passa a mentir junto. Por isso cada scanner é exercitado
contra DOIS fixtures — um que contém a violação e um que não contém.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit import _guard_harness as h

FIXTURES = Path(__file__).resolve().parent / "fixtures_guards"


def test_fontes_py_e_recursivo_e_absoluto() -> None:
    achados = h.fontes_py(FIXTURES)
    assert achados, "fixture vazio invalida o teste"
    assert all(p.is_absolute() for p in achados)
    assert {p.name for p in achados} == {"modulo.py"}
    assert len({p.parent.name for p in achados}) == 2  # com_violacao E sem_violacao


def test_escopo_vazio_levanta_em_vez_de_passar() -> None:
    """A regra que mata a vacuidade.

    Medido em 2026-09-06: `Path("src/mcp/tools").glob("*.py")` devolve 74
    arquivos da raiz do repo e ZERO de qualquer outro cwd — e o guard do
    relógio passava verde varrendo nada.
    """
    vazio = FIXTURES / "diretorio_que_nao_existe"
    with pytest.raises(h.EscopoVazioError):
        h.fontes_py(vazio)


def test_fontes_py_ignora_pycache(tmp_path: Path) -> None:
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "lixo.py").write_text("x = 1", encoding="utf-8")
    (tmp_path / "real.py").write_text("y = 2", encoding="utf-8")
    assert [p.name for p in h.fontes_py(tmp_path)] == ["real.py"]
