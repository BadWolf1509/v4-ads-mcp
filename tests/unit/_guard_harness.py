"""Travessia, escopo e casamento compartilhados pelos guards estruturais.

Existe porque 17 guards reimplementaram cada um a própria varredura, e cada
reimplementação trouxe o próprio defeito de cobertura: substring no texto do
arquivo, leitura linha a linha, `glob` não-recursivo, igualdade de nome de
classe em vez de subclasse, caminho relativo que vê zero arquivos fora da raiz.
Nenhum desses e um erro de raciocínio sobre a invariante — são todos erros de
varredura. Centralizar a varredura é o que impede o 18º.

Regra central: **um scanner que devolve zero arquivos levanta `EscopoVazioError`
em vez de devolver lista vazia.** Guard que varreu nada passa por vacuidade, e
foi exatamente assim que o guard do relógio ficou verde fora da raiz do repo
(medido em 2026-09-06).
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
SRC = RAIZ / "src"
TEMPLATES = SRC / "web" / "templates"
TESTES = RAIZ / "tests"

_IGNORADOS = frozenset(
    {
        "__pycache__",
        ".venv",
        ".git",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "node_modules",
    }
)


class EscopoVazioError(AssertionError):
    """Um guard que varre zero arquivos não é um guard."""


def _coletar(caminhos: Iterable[Path], *, raiz: Path, padrao: str) -> list[Path]:
    achados = sorted(p for p in caminhos if not (set(p.parts) & _IGNORADOS))
    if not achados:
        raise EscopoVazioError(
            f"escopo vazio: nenhum {padrao} sob {raiz}. Um guard que varre zero "
            "arquivos passa por vacuidade — foi assim que o guard do relógio "
            "ficou verde ao rodar de fora da raiz do repo (2026-09-06). "
            "Confira o caminho: ele precisa ser absoluto, derivado de __file__."
        )
    return achados


def fontes_py(raiz: Path | None = None) -> list[Path]:
    """Todo .py sob `raiz` (default: src/). Recursivo, absoluto, ordenado."""
    raiz = (raiz if raiz is not None else SRC).resolve()
    return _coletar(raiz.rglob("*.py"), raiz=raiz, padrao="*.py")


def testes_py(raiz: Path | None = None) -> list[Path]:
    """Todo .py sob tests/. Recursivo — subpacote novo não escapa."""
    raiz = (raiz if raiz is not None else TESTES).resolve()
    return _coletar(raiz.rglob("*.py"), raiz=raiz, padrao="*.py")


def templates_html(raiz: Path | None = None) -> list[Path]:
    raiz = (raiz if raiz is not None else TEMPLATES).resolve()
    return _coletar(raiz.rglob("*.html"), raiz=raiz, padrao="*.html")


def markdown(raiz: Path | None = None) -> list[Path]:
    """Todo .md do repositório, RECURSIVO — inclui docs/, que o guard do F113
    não enxergava (`_RAIZ.glob("*.md")` só pega a raiz)."""
    raiz = (raiz if raiz is not None else RAIZ).resolve()
    return _coletar(raiz.rglob("*.md"), raiz=raiz, padrao="*.md")


def workflows() -> list[Path]:
    d = RAIZ / ".github" / "workflows"
    return _coletar(d.glob("*.yml"), raiz=d, padrao="*.yml")


def arvore(caminho: Path) -> ast.Module:
    """AST de um arquivo, lido sempre em utf-8."""
    return ast.parse(caminho.read_text(encoding="utf-8"))


def rel(caminho: Path) -> str:
    """Caminho relativo à raiz, para mensagem de erro legível."""
    return str(caminho.relative_to(RAIZ)).replace("\\", "/")
