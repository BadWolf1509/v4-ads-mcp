"""BRL -> micros: arredondado, nunca truncado (preview == payload)."""

import ast
from pathlib import Path

import pytest

from src.google_ads.queries._common import brl_para_micros

SRC = Path(__file__).resolve().parents[2] / "src"


def test_valores_conhecidos() -> None:
    assert brl_para_micros(2.01) == 2_010_000
    assert brl_para_micros(4.10) == 4_100_000
    assert brl_para_micros(0.1) == 100_000


def test_varredura_de_centavos_e_multiplo_de_10000() -> None:
    for centavos in range(1, 100_001):
        micros = brl_para_micros(centavos / 100)
        assert micros == centavos * 10_000, centavos


def _trunca_micros(no: ast.AST) -> bool:
    """`int(<expr com * 1_000_000 / 1e6>)`: truncamento de produto float."""
    if not (
        isinstance(no, ast.Call)
        and isinstance(no.func, ast.Name)
        and no.func.id == "int"
        and no.args
    ):
        return False
    arg = no.args[0]
    if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name) and arg.func.id == "round":
        return False  # arredondado: e o que se quer
    for sub in ast.walk(arg):
        if (
            isinstance(sub, ast.BinOp)
            and isinstance(sub.op, ast.Mult)
            and any(
                isinstance(lado, ast.Constant)
                and isinstance(lado.value, (int, float))
                and lado.value == 1_000_000
                for lado in (sub.left, sub.right)
            )
        ):
            return True
    return False


def _ofensores(codigo: str) -> list[int]:
    return [n.lineno for n in ast.walk(ast.parse(codigo)) if _trunca_micros(n)]


@pytest.mark.parametrize(
    "codigo",
    [
        "int(x * 1_000_000)",
        "int(float(x) * 1_000_000)",
        "int(1_000_000 * x)",
        "int(x * 1e6)",
        "int(x * 1000000)",
        "int(a['k'] * 1_000_000)",
    ],
)
def test_guard_pega_as_formas_de_truncar(codigo: str) -> None:
    assert _ofensores(codigo) == [1]


@pytest.mark.parametrize(
    "codigo", ["int(round(Decimal(str(x)) * 1_000_000))", "int(x * 10_000)", "x * 1_000_000"]
)
def test_guard_nao_acusa_o_correto(codigo: str) -> None:
    assert _ofensores(codigo) == []


def test_nenhum_int_vezes_milhao_em_src() -> None:
    ofensores = [
        f"{p.relative_to(SRC)}:{n}"
        for p in SRC.rglob("*.py")
        for n in _ofensores(p.read_text(encoding="utf-8"))
    ]
    assert ofensores == []
