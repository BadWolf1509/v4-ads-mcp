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
Cada chave guarda o NUMERO de chamadas: funcao ja listada que ganha mais uma
chamada falha, e limpeza parcial (menos chamadas do que o permitido) obriga a
encolher a contagem. `create_pending` com alias de import (`as cp`) e resolvido
via `h.nomes_locais`; o codigo importa direto hoje (medido: sem alias).
O teste de "descreve a realidade" impede o ratchet de apodrecer: entrada que ja
foi consertada tem que sair da lista.
"""

from __future__ import annotations

import ast
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from tests.unit import _guard_harness as h

_ROTAS = h.SRC / "web" / "routes"
_TOOLS = h.SRC / "mcp" / "tools"

_METODOS_DE_BANCO = frozenset({"fetch", "fetchrow", "fetchval", "execute", "executemany"})

# (arquivo relativo a raiz, funcao de topo que contem a chamada).
_SQL_EM_ROTA_CONHECIDO: dict[tuple[str, str], int] = {
    ("src/web/routes/_acesso.py", "aplicar_toggle"): 1,
    ("src/web/routes/accounts.py", "accounts_page"): 1,
    ("src/web/routes/accounts.py", "accounts_revoke_connection"): 1,
    ("src/web/routes/admin_access.py", "admin_access"): 1,
    ("src/web/routes/admin_access.py", "admin_access_meta"): 1,
    ("src/web/routes/admin_access.py", "admin_access_meta_by_manager"): 2,
    ("src/web/routes/admin_access.py", "admin_access_meta_manager_detail"): 1,
    ("src/web/routes/admin_access.py", "admin_access_by_manager"): 2,
    ("src/web/routes/admin_access.py", "admin_access_manager_detail"): 1,
    ("src/web/routes/admin_invites.py", "admin_invites"): 1,
    ("src/web/routes/admin_invites.py", "admin_invites_new"): 1,
    ("src/web/routes/admin_invites.py", "admin_invites_cancel"): 1,
    ("src/web/routes/admin_overview.py", "admin_index"): 3,
    ("src/web/routes/dashboard.py", "dashboard"): 1,
}

# (arquivo, funcao) -> numero de chamadas a `create_pending` fora de `_mutate_common.py`.
_CREATE_PENDING_FORA_DO_HELPER: dict[tuple[str, str], int] = {
    ("src/mcp/tools/bulk_pause_by_query.py", "bulk_pause_by_query"): 1,
    ("src/mcp/tools/create_and_link_assets.py", "create_and_link_assets"): 1,
    ("src/mcp/tools/import_offline_conversions.py", "import_offline_conversions"): 1,
    ("src/mcp/tools/update_keyword_status.py", "update_keyword_status"): 1,
    ("src/mcp/tools/upload_customer_match_list.py", "upload_customer_match_list"): 1,
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


def _e_create_pending(nomes: frozenset[str]) -> Callable[[ast.Call], bool]:
    def casa(call: ast.Call) -> bool:
        f = call.func
        return (isinstance(f, ast.Name) and f.id in nomes) or (
            isinstance(f, ast.Attribute) and f.attr in nomes
        )

    return casa


def _contagem(
    arquivos: list[Path], fabrica: Callable[[Path], Callable[[ast.Call], bool]]
) -> Counter[tuple[str, str]]:
    return Counter((h.rel(a), fn) for a in arquivos for fn, _ in _sitios(a, fabrica(a)))


def _sql_em_rotas() -> Counter[tuple[str, str]]:
    return _contagem(h.fontes_py(_ROTAS), lambda _a: _e_sql)


def _create_pending_fora() -> Counter[tuple[str, str]]:
    arquivos = [a for a in h.fontes_py(_TOOLS) if a.name != "_mutate_common.py"]
    return _contagem(
        arquivos,
        lambda a: _e_create_pending(frozenset(h.nomes_locais(h.arvore(a), "create_pending"))),
    )


def _excedentes(
    medido: Counter[tuple[str, str]], permitido: dict[tuple[str, str], int]
) -> dict[tuple[str, str], tuple[int, int]]:
    """Chave nova ou contagem acima do permitido: `chave -> (medido, permitido)`."""
    return {k: (n, permitido.get(k, 0)) for k, n in medido.items() if n > permitido.get(k, 0)}


def _folgas(
    medido: Counter[tuple[str, str]], permitido: dict[tuple[str, str], int]
) -> dict[tuple[str, str], tuple[int, int]]:
    """Chave sumida ou contagem abaixo do permitido: `chave -> (medido, permitido)`."""
    return {k: (medido.get(k, 0), n) for k, n in permitido.items() if medido.get(k, 0) < n}


def test_rota_nao_chama_conn_direto() -> None:
    novos = _excedentes(_sql_em_rotas(), _SQL_EM_ROTA_CONHECIDO)
    assert not novos, (
        "rota do painel com SQL direto (fetch/fetchrow/fetchval/execute/"
        f"executemany em qualquer receptor) acima do permitido, (medido, permitido): {novos}. "
        "Mova a consulta para uma funcao de repositorio; a allowlist so encolhe."
    )


def test_create_pending_so_no_helper() -> None:
    novos = _excedentes(_create_pending_fora(), _CREATE_PENDING_FORA_DO_HELPER)
    assert not novos, (
        f"create_pending fora de _mutate_common.py acima do permitido, (medido, permitido): {novos}. "
        "Use o helper de preview; a allowlist so encolhe."
    )


def test_a_allowlist_de_sql_descreve_a_realidade() -> None:
    folgas = _folgas(_sql_em_rotas(), _SQL_EM_ROTA_CONHECIDO)
    assert folgas == {}, f"ja consertado, encolha a allowlist, (medido, permitido): {folgas}"


def test_a_allowlist_de_create_pending_descreve_a_realidade() -> None:
    folgas = _folgas(_create_pending_fora(), _CREATE_PENDING_FORA_DO_HELPER)
    assert folgas == {}, f"ja consertado, encolha a allowlist, (medido, permitido): {folgas}"
