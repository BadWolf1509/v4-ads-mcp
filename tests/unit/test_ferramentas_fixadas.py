"""As ferramentas que decidem o gate tem versao fixa, e o gate local confere a instalada.

Em 10/11 o #233 passou no gate local (ruff 0.15.18 da `.venv`) e caiu no CI, que
instalou o ruff 0.17.4 resolvendo `ruff>=0.7.0` (SIM102). O mypy tinha a mesma
deriva medida em 11/11 (2.1.0 local x 2.4.1 no CI). O pin fecha o CI; a checagem
no gate fecha a `.venv` que ficou para tras.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

from _runner import BASE_STEPS  # noqa: E402
from check_ferramentas_fixadas import (  # noqa: E402
    FERRAMENTAS,
    divergencias,
    pins_do_pyproject,
)


def test_ferramentas_do_gate_estao_fixadas_com_igualdade_no_pyproject() -> None:
    pins = pins_do_pyproject(RAIZ / "pyproject.toml")
    assert set(FERRAMENTAS) <= set(pins), f"sem pin '==': {set(FERRAMENTAS) - set(pins)}"
    for nome in FERRAMENTAS:
        assert pins[nome].count(".") >= 2, f"{nome}=={pins[nome]} nao e versao exata"


def test_pins_ignora_especificador_que_nao_e_igualdade(tmp_path: Path) -> None:
    arquivo = tmp_path / "pyproject.toml"
    arquivo.write_text(
        '[project.optional-dependencies]\ndev = ["ruff>=0.7.0", "mypy==2.4.1", "x~=1.0"]\n',
        encoding="utf-8",
    )
    assert pins_do_pyproject(arquivo) == {"mypy": "2.4.1"}


@pytest.mark.parametrize(
    ("instaladas", "esperado"),
    [
        ({"ruff": "0.17.4", "mypy": "2.4.1"}, []),
        ({"ruff": "0.15.18", "mypy": "2.4.1"}, ["ruff: instalado 0.15.18, fixado 0.17.4"]),
        ({"ruff": "0.17.4", "mypy": None}, ["mypy: nao instalado, fixado 2.4.1"]),
    ],
)
def test_divergencias_compara_instalada_com_fixada(
    instaladas: dict[str, str | None], esperado: list[str]
) -> None:
    pins = {"ruff": "0.17.4", "mypy": "2.4.1"}
    assert divergencias(pins, instaladas.get) == esperado


def test_gate_confere_as_versoes_antes_do_ruff() -> None:
    nomes = [s.name for s in BASE_STEPS]
    assert nomes[0] == "ferramentas na versao fixada", nomes
