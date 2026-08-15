"""Guards estruturais: varrem o source pra impedir reincidência de classes de bug.

Cada guard aqui existe porque a classe já mordeu em produção e a proteção era
"lembrar de fazer grep manual" (documentada no CLAUDE.md). Um guard automatizado
transforma a convenção num teste que falha no commit em vez de num incidente.

- F57 (Google): call-site de build_client_for_manager sem ensure_account_access
  → vazou existência/schema de qualquer conta da MCC (o validate_gaql ficou
  desguarnecido até a auditoria de 2026-06-20).
- F57-Meta: chamada à Graph API fora de run_meta_graph_get → pula o hard-gate
  (o freio do Modelo B é a matriz de acesso; o token é compartilhado).
- F58: conn.cursor() sem async with conn.transaction() → asyncpg exige transação
  pra server-side cursor (o CSV export quebrou em prod porque nenhum teste iterou).
- F83: I/O de bookkeeping num `finally` sem best_effort → exceção ali DESCARTA o
  `return` pendente do `try`, virando erro numa mutação já aplicada no provider
  (e apagando a própria linha de audit que deveria registrá-la).
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"


def _py_files() -> list[Path]:
    return [p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts]


def _calls(node: ast.AST, name: str) -> bool:
    """True se a subárvore contém chamada a `name` (Name ou Attribute)."""
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        if isinstance(func, ast.Name) and func.id == name:
            return True
        if isinstance(func, ast.Attribute) and func.attr == name:
            return True
    return False


def test_build_client_for_manager_callsites_have_gate() -> None:
    """F57: todo arquivo que CHAMA build_client_for_manager também chama
    ensure_account_access. client.py o DEFINE (allowlist)."""
    definer = SRC / "google_ads" / "client.py"
    offenders = []
    for p in _py_files():
        if p == definer:
            continue
        text = p.read_text(encoding="utf-8")
        if "build_client_for_manager(" in text and "ensure_account_access(" not in text:
            offenders.append(str(p.relative_to(SRC)))
    assert not offenders, (
        "F57 — call-site de build_client_for_manager SEM ensure_account_access: "
        f"{offenders}. Todo caminho que builda o client Google precisa do hard-gate "
        "no mesmo fluxo (grep TODA função que chama build_client_for_manager)."
    )


def test_meta_graph_execution_is_contained() -> None:
    """F57-Meta: build_meta_api (o factory de execução com o system-user token) só
    pode ser chamado dentro de run_meta_graph_get (reports.py), que aplica o gate.
    client.py o DEFINE. Um tool que chame direto pularia o hard-gate incondicional."""
    allowed = {
        SRC / "meta_ads" / "client.py",  # define build_meta_api
        SRC / "meta_ads" / "reports.py",  # run_meta_graph_get — único executor
    }
    offenders = []
    for p in _py_files():
        if p in allowed:
            continue
        if "build_meta_api(" in p.read_text(encoding="utf-8"):
            offenders.append(str(p.relative_to(SRC)))
    assert not offenders, (
        "F57-Meta — build_meta_api chamado fora de reports.py: "
        f"{offenders}. Toda leitura Meta deve passar por run_meta_graph_get "
        "(gate can_manager_access + audit + BUC)."
    )


def test_cursor_usage_is_wrapped_in_transaction() -> None:
    """F58: arquivo que usa conn.cursor() (server-side cursor) precisa também
    de conn.transaction() — asyncpg exige transação explícita, senão o generator
    quebra no primeiro fetch (o CSV export foi pra prod quebrado assim)."""
    offenders = []
    for p in _py_files():
        text = p.read_text(encoding="utf-8")
        if ".cursor(" in text and "conn.transaction()" not in text:
            offenders.append(str(p.relative_to(SRC)))
    assert not offenders, (
        "F58 — .cursor() sem conn.transaction() no mesmo arquivo: "
        f"{offenders}. async for row in conn.cursor(...) PRECISA de "
        "async with conn.transaction()."
    )


def test_gaql_nao_usa_doubling_de_aspas() -> None:
    """F87: GAQL escapa string literal com BARRA INVERTIDA, não com doubling de SQL.

    Verificado empiricamente contra a API real: `IN ('O''Brien')` retorna
    `invalid value 'Brien'`, enquanto `IN ('O\\'Brien')` valida. O padrão `''`
    veio de reflexo de SQL e quebrava nomes legítimos (`Lead - D'Or`).

    O guard é AST, não grep de texto. A primeira versão casava a linha crua e o
    ÚNICO infrator que ela achou foi a docstring de `_gaql.py`, que cita o padrão
    antigo justamente pra explicar por que ele é errado — a armadilha registrada
    na nota de método de 2026-08-11: a prosa que descreve a regra dispara o guard
    que a aplica. Casando a CHAMADA no AST, comentário e docstring ficam
    invisíveis por construção.
    """
    offenders = []
    for p in _py_files():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover — src sempre parseia
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or len(node.args) != 2:
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "replace"):
                continue
            a, b = node.args
            if (
                isinstance(a, ast.Constant)
                and isinstance(b, ast.Constant)
                and a.value == "'"
                and b.value == "''"
            ):
                offenders.append(f"{p.relative_to(SRC)}:{node.lineno}")
    assert not offenders, (
        f"F87 — doubling de aspas ('') pra escapar GAQL: {offenders}. "
        "GAQL não é SQL nisso: use gaql_string_literal/gaql_escape de "
        "src/google_ads/queries/_gaql.py (barra invertida, e a barra vem primeiro)."
    )


def test_finally_bookkeeping_is_best_effort() -> None:
    """F83: I/O de bookkeeping (audit/quota) dentro de `finally` precisa estar sob
    best_effort.

    Exceção levantada num `finally` DESCARTA o `return` pendente do `try`. Como os
    executores adquirem conexão ali pra gravar audit e reconciliar quota, uma
    conexão asyncpg stale (F76) fazia uma mutação JÁ APLICADA no Google voltar como
    erro — o gestor via falha, o cliente LLM tendia a re-tentar operação
    não-idempotente, e a linha de audit não era gravada.

    O guard é por BLOCO (não por arquivo): cada statement do `finally` que adquire
    conexão tem que estar sob best_effort no mesmo statement.
    """
    offenders = []
    for p in _py_files():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover — src sempre parseia
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try) or not node.finalbody:
                continue
            for stmt in node.finalbody:
                if _calls(stmt, "acquire") and not _calls(stmt, "best_effort"):
                    offenders.append(f"{p.relative_to(SRC)}:{stmt.lineno}")
    assert not offenders, (
        "F83 — pool.acquire() em `finally` sem best_effort: "
        f"{offenders}. Bookkeeping OBSERVA a operação, não decide o resultado dela: "
        "envolva com `async with best_effort(...)` (src/governance/bookkeeping.py), "
        "senão a falha do audit derruba a mutação já aplicada."
    )
