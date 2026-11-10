"""Ratchets de camada: SQL direto nas rotas do painel e `create_pending` nas tools.

Dois acoplamentos que a arquitetura em camadas proíbe e que o código já tem em
resíduo conhecido:

1. Rota do painel (`src/web/routes/*.py`) fala com o banco por função de
   repositório; chamar `fetch`/`fetchrow`/`fetchval`/`execute`/`executemany`
   direto na rota espalha SQL pela camada HTTP.
2. Tool de mutação cria a confirmação pendente pelo helper de preview
   (`_mutate_common.py`); chamar `create_pending` por conta própria duplica o
   envelope e deixa a tool escapar das garantias do helper.

Cada residuo e uma allowlist que SO ENCOLHE (D3 e G2 a levam a vazio). A chave e
`(arquivo, funcao)`, nunca a linha, para a allowlist nao quebrar a cada edicao.
O teste de "descreve a realidade" impede o ratchet de apodrecer: entrada que ja
foi consertada tem que sair da lista.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path

from tests.unit import _guard_harness as h

_ROTAS = h.SRC / "web" / "routes"
_TOOLS = h.SRC / "mcp" / "tools"

_METODOS_DE_BANCO = frozenset({"fetch", "fetchrow", "fetchval", "execute", "executemany"})

# (arquivo relativo a raiz, funcao de topo que contem a chamada).
_SQL_EM_ROTA_CONHECIDO: set[tuple[str, str]] = {
    ("src/web/routes/_acesso.py", "aplicar_toggle"),
    ("src/web/routes/accounts.py", "accounts_page"),
    ("src/web/routes/accounts.py", "accounts_revoke_connection"),
    ("src/web/routes/admin_access.py", "admin_access"),
    ("src/web/routes/admin_access.py", "admin_access_meta"),
    ("src/web/routes/admin_access.py", "admin_access_meta_by_manager"),
    ("src/web/routes/admin_access.py", "admin_access_meta_manager_detail"),
    ("src/web/routes/admin_access.py", "admin_access_by_manager"),
    ("src/web/routes/admin_access.py", "admin_access_manager_detail"),
    ("src/web/routes/admin_invites.py", "admin_invites"),
    ("src/web/routes/admin_invites.py", "admin_invites_new"),
    ("src/web/routes/admin_invites.py", "admin_invites_cancel"),
    ("src/web/routes/admin_overview.py", "admin_index"),
    ("src/web/routes/dashboard.py", "dashboard"),
}

# Nome da funcao que chama `create_pending` fora de `_mutate_common.py`.
_CREATE_PENDING_FORA_DO_HELPER: set[str] = {
    "bulk_pause_by_query",
    "create_and_link_assets",
    "import_offline_conversions",
    "update_keyword_status",
    "upload_customer_match_list",
}


def _sitios(arquivo: Path, casa: Callable[[ast.Call], bool]) -> list[tuple[str, int]]:
    """`(funcao mais externa, linha)` de cada chamada que `casa(call)` aceita.

    A funcao e a MAIS EXTERNA (de topo, ou o metodo da classe): lambda e funcao
    aninhada sao atribuidas a ela, porque a rota e a unidade que o ratchet
    cobra e `lambda c: c.fetch(...)` e SQL direto da mesma rota. Chamada em
    nivel de modulo vira `<modulo>`.
    """
    achados: list[tuple[str, int]] = []

    def visita(no: ast.AST, externa: str) -> None:
        for filho in ast.iter_child_nodes(no):
            nome = externa
            if externa == "<modulo>" and isinstance(filho, ast.FunctionDef | ast.AsyncFunctionDef):
                nome = filho.name
            if isinstance(filho, ast.Call) and casa(filho):
                achados.append((nome, filho.lineno))
            visita(filho, nome)

    visita(h.arvore(arquivo), "<modulo>")
    return achados


def _e_sql(call: ast.Call) -> bool:
    return isinstance(call.func, ast.Attribute) and call.func.attr in _METODOS_DE_BANCO


def _e_create_pending(call: ast.Call) -> bool:
    f = call.func
    return (isinstance(f, ast.Name) and f.id == "create_pending") or (
        isinstance(f, ast.Attribute) and f.attr == "create_pending"
    )


def _sql_em_rotas() -> set[tuple[str, str]]:
    arquivos = h.fontes_py(_ROTAS)
    return {(h.rel(a), fn) for a in arquivos for fn, _ in _sitios(a, _e_sql)}


def _create_pending_fora() -> set[str]:
    arquivos = [a for a in h.fontes_py(_TOOLS) if a.name != "_mutate_common.py"]
    return {fn for a in arquivos for fn, _ in _sitios(a, _e_create_pending)}


def test_rota_nao_chama_conn_direto() -> None:
    novos = _sql_em_rotas() - _SQL_EM_ROTA_CONHECIDO
    assert not novos, (
        "rota do painel com SQL direto (fetch/fetchrow/fetchval/execute/"
        f"executemany em qualquer receptor): {sorted(novos)}. Mova a consulta "
        "para uma funcao de repositorio; a allowlist so encolhe."
    )


def test_create_pending_so_no_helper() -> None:
    novos = _create_pending_fora() - _CREATE_PENDING_FORA_DO_HELPER
    assert not novos, (
        f"create_pending chamado fora de _mutate_common.py: {sorted(novos)}. "
        "Use o helper de preview; a allowlist so encolhe."
    )


def test_a_allowlist_de_sql_descreve_a_realidade() -> None:
    obsoletas = _SQL_EM_ROTA_CONHECIDO - _sql_em_rotas()
    assert obsoletas == set(), f"entrada ja consertada, tire da allowlist: {sorted(obsoletas)}"


def test_a_allowlist_de_create_pending_descreve_a_realidade() -> None:
    obsoletas = _CREATE_PENDING_FORA_DO_HELPER - _create_pending_fora()
    assert obsoletas == set(), f"entrada ja consertada, tire da allowlist: {sorted(obsoletas)}"
