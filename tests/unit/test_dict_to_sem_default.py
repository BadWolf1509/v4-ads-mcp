"""Guard: adaptador `dict_to_*` nao inventa valor para campo ausente.

`d.get("impressions", 0)` transforma "o formatter esqueceu o campo" em "zero
impressoes" — o relatorio sai verde e errado. O campo ausente e bug do
formatter, e tem que estourar `KeyError`. Os campos que PODEM faltar de
proposito usam `.get(k)` de um argumento (default `None` explicito).
"""

from __future__ import annotations

import ast

import pytest

from tests.unit import _guard_harness as h

_GOOGLE_ADS = h.SRC / "google_ads"


def _e_chamada(no: ast.AST, metodo: str) -> bool:
    return (
        isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute) and no.func.attr == metodo
    )


def _colecao_vazia(no: ast.AST) -> bool:
    return (isinstance(no, ast.List | ast.Tuple) and not no.elts) or (
        isinstance(no, ast.Call)
        and isinstance(no.func, ast.Name)
        and no.func.id in ("list", "tuple")
        and not no.args
    )


def _inventa_valor(no: ast.AST) -> bool:
    """As formas de preencher campo ausente que o guard ja viu ou que a revisao listou.

    - `d.get(k, 0)` / `d.pop(k, 0)` — default explicito (a forma original);
    - `d.get(k) or 0` — o `None` do ausente vira o valor do lado direito
      (follow-up da Parte I, 11/11: passava no guard antigo);
    - `d.setdefault(k, ...)` — grava o default no proprio dict;
    - `{**DEFAULTS, **d}` / `{"impressions": 0, **d}` — mescla com defaults:
      dict literal com desempacotamento E mais alguma entrada;
    - `DEFAULTS | d` / `d | {...}` — a mesma mescla pelo operador.
    """
    if (_e_chamada(no, "get") or _e_chamada(no, "pop")) and isinstance(no, ast.Call):
        return (len(no.args) + len(no.keywords)) >= 2
    if _e_chamada(no, "setdefault"):
        return True
    if isinstance(no, ast.BoolOp) and isinstance(no.op, ast.Or):
        # `d.get(k) or []`/`or ()` fica de fora: para campo REPETIDO do proto
        # (FieldMask, listas) "ausente" e "vazio" sao o mesmo estado — nao ha
        # valor inventado, ha a colecao vazia que o proto ja quer dizer.
        if _colecao_vazia(no.values[-1]):
            return False
        return any(_e_chamada(v, "get") for v in no.values[:-1])
    if isinstance(no, ast.Dict):
        return None in no.keys and len(no.keys) >= 2
    if isinstance(no, ast.BinOp) and isinstance(no.op, ast.BitOr):
        return isinstance(no.left, ast.Dict) or isinstance(no.right, ast.Dict)
    return False


def _get_com_default(fonte: str) -> list[tuple[str, int]]:
    """(funcao, linha) de cada forma de inventar valor dentro de `dict_to_*`."""
    achados: list[tuple[str, int]] = []
    for fn in h.funcoes(ast.parse(fonte)):
        if not fn.name.startswith("dict_to_"):
            continue
        for no in ast.walk(fn):
            if _inventa_valor(no):
                achados.append((fn.name, no.lineno))
    return sorted(set(achados))


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


def _fonte(corpo: str) -> str:
    return "def dict_to_x(d):\n    return " + corpo + "\n"


@pytest.mark.parametrize(
    "corpo",
    [
        'int(d.get("impressions") or 0)',
        'int(d.pop("impressions", 0))',
        'd.setdefault("impressions", 0)',
        "{**_PADRAO, **d}",
        '{"impressions": 0, **d}',
        'd | {"impressions": 0}',
        '_PADRAO | d if False else {**d, "clicks": 0}',
    ],
)
def test_scanner_enxerga_as_formas_alem_do_get(corpo: str) -> None:
    """O guard antigo (so `.get` com 2 args) devolvia [] para todas estas."""
    assert _get_com_default(_fonte(corpo)), corpo


@pytest.mark.parametrize(
    "corpo",
    ['d["impressions"]', 'd.get("campaign_id")', "{**d}", 'tuple(d.get("changed_fields") or [])'],
)
def test_scanner_nao_acusa_leitura_estrita(corpo: str) -> None:
    """Contraprova: copiar o dict, ler estrito e `.get` de um argumento passam."""
    assert not _get_com_default(_fonte(corpo)), corpo
