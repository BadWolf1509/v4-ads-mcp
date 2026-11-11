"""Guard: o fuso do painel tem UMA fonte — `FUSO_PAINEL` em `src/web/numeros.py`.

Antes, o literal `America/Sao_Paulo` morava em tres lugares do painel (o
`ZoneInfo` de `numeros.py`, o `_BRASILIA` de `templating.py` e o `AT TIME ZONE`
dentro do SQL), mais um default morto em `Settings.app_timezone` que nada lia.
Trocar o fuso do painel exigia lembrar dos quatro.

AST e nao grep: docstring e comentario CITAM o fuso para explicar (clock.py,
account_clock.py), e isso nao e uma segunda fonte. So conta literal de codigo.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.unit import _guard_harness as h

FUSO = "America/Sao_Paulo"
ONDE_MORA = "src/web/numeros.py"

# Piso do escopo: `src/` tem centenas de .py. `fontes_py` so levanta com ZERO.
_PISO_DE_FONTES = 100


def _literais_de_codigo(arv: ast.Module) -> list[tuple[int, str]]:
    """`(linha, texto)` de todo literal string que NAO e docstring."""
    ids_docstring = h._nos_de_docstring(arv)
    return [
        (no.lineno, h._texto_logico(no))
        for no in h._literais_de_string(arv)
        if not (isinstance(no, ast.Constant) and id(no) in ids_docstring)
    ]


def _ocorrencias(fontes: list[Path]) -> list[str]:
    achados: list[str] = []
    for arquivo in fontes:
        for linha, texto in _literais_de_codigo(h.arvore(arquivo)):
            if FUSO in texto:
                achados.append(f"{h.rel(arquivo)}:{linha}")
    return achados


def test_escopo_nao_e_vacuo() -> None:
    assert len(h.fontes_py()) >= _PISO_DE_FONTES


def test_fuso_do_painel_so_em_numeros() -> None:
    achados = _ocorrencias(h.fontes_py())
    fora = [a for a in achados if not a.startswith(ONDE_MORA + ":")]
    assert not fora, (
        f"o literal {FUSO!r} so pode existir em {ONDE_MORA} (FUSO_PAINEL); "
        f"importe FUSO_PAINEL em vez de repetir: {fora}"
    )
    # A fonte tem que existir: sem ela o teste acima passaria por vacuidade.
    assert len(achados) == 1, f"esperava exatamente 1 definicao em {ONDE_MORA}: {achados}"


def test_templates_nao_repetem_o_fuso() -> None:
    com_fuso = [h.rel(t) for t in h.templates_html() if FUSO in t.read_text(encoding="utf-8")]
    assert not com_fuso, f"template com o literal {FUSO!r}: {com_fuso}"


def test_autoteste_do_scanner_ve_o_literal_e_ignora_docstring() -> None:
    arv = ast.parse(
        f'"""doc cita {FUSO}."""\ndef f():\n    """tambem {FUSO}."""\n    return "x {FUSO} y"\n'
    )
    achados = _literais_de_codigo(arv)
    assert [t for _, t in achados if FUSO in t] == [f"x {FUSO} y"]
