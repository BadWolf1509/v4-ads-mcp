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


def _returns_da_funcao(src: str, nome: str) -> list[ast.expr]:
    tree = ast.parse(src)
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == nome
    )
    # Only direct returns in the function body, not in nested functions
    returns = []
    for node in fn.body:
        for n in ast.walk(node):
            if isinstance(n, ast.Return) and n.value is not None and not _in_nested_function(n, fn):
                returns.append(n.value)
    return returns


def _in_nested_function(
    ret_node: ast.Return, parent_fn: ast.FunctionDef | ast.AsyncFunctionDef
) -> bool:
    """Check if a return node is inside a nested function within parent_fn."""
    for node in ast.walk(parent_fn):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node is not parent_fn
            and any(n is ret_node for n in ast.walk(node))
        ):
            return True
    return False


def _e_chamada_a(expr: ast.expr, nomes: set[str]) -> bool:
    return isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id in nomes


def _e_dict_de_no_changes(expr: ast.expr) -> bool:
    """A unica resposta montada a mao que a spec sanciona (§4.4): o no-op sem token."""
    return isinstance(expr, ast.Dict) and any(
        isinstance(k, ast.Constant) and k.value == "no_changes" for k in expr.keys
    )


def test_todo_return_de_update_ad_schedule_e_envelope_do_compartilhado_ou_o_no_changes() -> None:
    """Spec §8.10 pelo USO, nao pela presenca: um dict a mao no return com uma chamada morta
    a preview_envelope em outro lugar passaria pela contagem — e exatamente o adjacente."""
    src = Path("src/mcp/tools/update_ad_schedule.py").read_text(encoding="utf-8")
    returns = _returns_da_funcao(src, "update_ad_schedule")
    assert returns, "a funcao tem que ter returns"
    ruins = [
        ast.dump(r)[:80]
        for r in returns
        if not (_e_chamada_a(r, {"preview_envelope", "error_envelope"}) or _e_dict_de_no_changes(r))
    ]
    assert ruins == [], f"return fora do envelope compartilhado (e nao e o no_changes): {ruins}"
