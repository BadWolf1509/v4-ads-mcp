"""Guard: adaptador `dict_to_*` nao inventa valor para campo ausente.

`d.get("impressions", 0)` transforma "o formatter esqueceu o campo" em "zero
impressoes" — o relatorio sai verde e errado. O campo ausente e bug do
formatter, e tem que estourar `KeyError`. Os campos que PODEM faltar de
proposito usam `.get(k)` de um argumento (default `None` explicito).
"""

from __future__ import annotations

import ast

from tests.unit import _guard_harness as h

_GOOGLE_ADS = h.SRC / "google_ads"


def _get_com_default(fonte: str) -> list[tuple[str, int]]:
    """(funcao, linha) de cada `.get(...)` com 2+ argumentos dentro de `dict_to_*`."""
    achados: list[tuple[str, int]] = []
    for fn in h.funcoes(ast.parse(fonte)):
        if not fn.name.startswith("dict_to_"):
            continue
        for no in ast.walk(fn):
            if (
                isinstance(no, ast.Call)
                and isinstance(no.func, ast.Attribute)
                and no.func.attr == "get"
                and (len(no.args) + len(no.keywords)) >= 2
            ):
                achados.append((fn.name, no.lineno))
    return achados


def _funcoes_dict_to(fonte: str) -> int:
    return sum(1 for fn in h.funcoes(ast.parse(fonte)) if fn.name.startswith("dict_to_"))


def test_dict_to_sem_default() -> None:
    total_funcoes = 0
    violacoes: list[str] = []
    for caminho in h.fontes_py(_GOOGLE_ADS):
        fonte = caminho.read_text(encoding="utf-8")
        total_funcoes += _funcoes_dict_to(fonte)
        violacoes += [f"{h.rel(caminho)}:{ln} {nome}" for nome, ln in _get_com_default(fonte)]
    assert total_funcoes > 0, "vacuidade: nenhuma funcao dict_to_* encontrada em src/google_ads"
    assert not violacoes, (
        "`.get(k, default)` em dict_to_* inventa valor para campo ausente; use d[k] "
        "(ou .get(k) de um argumento se o campo pode faltar de proposito): " + "; ".join(violacoes)
    )


def test_scanner_enxerga_get_com_default() -> None:
    """Autoteste do scanner: a sabotagem em memoria tem que ser pega."""
    ruim = 'def dict_to_x(d):\n    return int(d.get("impressions", 0))\n'
    bom = 'def dict_to_x(d):\n    return d["impressions"], d.get("campaign_id")\n'
    fora = 'def outra(d):\n    return d.get("a", 0)\n'
    assert _get_com_default(ruim) == [("dict_to_x", 2)]
    assert _get_com_default(bom) == []
    assert _get_com_default(fora) == []
