#!/usr/bin/env python3
"""Confere que o ruff e o mypy instalados sao os fixados no pyproject.

O CI instala `.[dev]` e pega o pin; a `.venv` local fica com o que foi instalado
um dia. Sem esta checagem o gate local roda outra versao e aprova o que o CI
reprova (10/11, #233: SIM102 so existia no ruff do CI).
"""

from __future__ import annotations

import re
import sys
import tomllib
from collections.abc import Callable
from importlib import metadata
from pathlib import Path

FERRAMENTAS: tuple[str, ...] = ("ruff", "mypy")

_PIN = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*==\s*([0-9][0-9A-Za-z.]*)\s*$")


def pins_do_pyproject(caminho: Path) -> dict[str, str]:
    """Nome -> versao das dependencias dev fixadas com `==` (as demais ficam de fora)."""
    dados = tomllib.loads(caminho.read_text(encoding="utf-8"))
    dev = dados.get("project", {}).get("optional-dependencies", {}).get("dev", [])
    pins: dict[str, str] = {}
    for requisito in dev:
        casou = _PIN.match(requisito)
        if casou:
            pins[casou.group(1).lower()] = casou.group(2)
    return pins


def _instalada(nome: str) -> str | None:
    try:
        return metadata.version(nome)
    except metadata.PackageNotFoundError:
        return None


def divergencias(pins: dict[str, str], instalada: Callable[[str], str | None]) -> list[str]:
    """Uma linha por ferramenta cuja versao instalada difere da fixada."""
    linhas: list[str] = []
    for nome in FERRAMENTAS:
        fixada = pins.get(nome)
        if fixada is None:
            linhas.append(f"{nome}: sem pin '==' no pyproject")
            continue
        atual = instalada(nome)
        if atual is None:
            linhas.append(f"{nome}: nao instalado, fixado {fixada}")
        elif atual != fixada:
            linhas.append(f"{nome}: instalado {atual}, fixado {fixada}")
    return linhas


def main() -> int:
    raiz = Path(__file__).resolve().parent.parent
    pins = pins_do_pyproject(raiz / "pyproject.toml")
    linhas = divergencias(pins, _instalada)
    if not linhas:
        return 0
    for linha in linhas:
        print(linha, file=sys.stderr)
    alvo = " ".join(f"{n}=={pins[n]}" for n in FERRAMENTAS if n in pins)
    print(f"Atualize a .venv: python -m pip install {alvo}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
