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
3. GAQL fica na camada de queries (`src/google_ads/queries/`, `preflight.py`):
   tool que escreve `SELECT ... FROM <recurso>` por conta propria espalha
   consulta pela camada MCP (4 tools hoje).
4. A janela de data (`segments.date BETWEEN`) tem definicao unica em
   `queries/_common.py`; reescreve-la a mao e como nasce a janela divergente.
"""

from __future__ import annotations

import ast
import re
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

# (arquivo, funcao) -> numero de literais GAQL (`SELECT ... FROM <recurso>`) nas tools.
_GAQL_NAS_TOOLS: dict[tuple[str, str], int] = {
    ("src/mcp/tools/apply_audience.py", "_validate_user_interest_taxonomies"): 1,
    ("src/mcp/tools/update_ad_group_bid.py", "update_ad_group_bid"): 1,
    ("src/mcp/tools/update_campaign_budget.py", "update_campaign_budget"): 1,
    ("src/mcp/tools/update_keyword_bid.py", "update_keyword_bid"): 1,
}

# (arquivo, funcao) -> numero de literais com `segments.date BETWEEN` fora de `_common.py`.
_JANELA_FORA_DO_COMMON: dict[tuple[str, str], int] = {
    ("src/google_ads/queries/audit_competitor_keywords.py", "build_search_terms_query"): 1,
    ("src/google_ads/queries/audit_quality_score.py", "build_audit_quality_score_query"): 1,
}

_COMMON = h.SRC / "google_ads" / "queries" / "_common.py"
_GAQL = re.compile(r"\bSELECT\b.+\bFROM\s+[a-z_]+", re.DOTALL)
_JANELA = re.compile(r"segments\.date BETWEEN")

# Regra estrutural que separa GAQL de TEXTO que a cita. Nas tools, GAQL real e
# sempre atribuido a uma variavel (`query = f"""SELECT ..."""`); o texto que so
# MENCIONA `SELECT/FROM` ou `segments.date BETWEEN` viaja como valor de keyword
# de prosa numa chamada: `description=` do `register_tool` (bulk_pause_by_query)
# e `to_apply=` do envelope de preview (upload_customer_match_list, uma dica de
# `run_gaql ... 'SELECT ... FROM ...'`). Docstring e comentario nao chegam aqui
# (`_nos_de_docstring`; comentario nem e literal). A lista e FECHADA de proposito:
# `query=f"SELECT ..."` passado a um executor continua sendo GAQL e continua pego.
_KWARGS_DE_PROSA = frozenset({"description", "to_apply"})


def _literais_por_funcao(arquivo: Path) -> list[tuple[str, str]]:
    """`(funcao mais externa, texto logico)` de cada literal que NAO e prosa.

    Fora: docstring e valor de keyword em `_KWARGS_DE_PROSA`. Literais
    adjacentes (`"SELECT a " "FROM b"`) e f-strings ja chegam fundidos pelo
    parser, e `_texto_logico` troca os `{expr}` por `X`.
    """
    arv = h.arvore(arquivo)
    docstrings = h._nos_de_docstring(arv)
    achados: list[tuple[str, str]] = []

    def visita(no: ast.AST, externa: str) -> None:
        for filho in ast.iter_child_nodes(no):
            nome = externa
            if externa == "<modulo>" and isinstance(filho, ast.FunctionDef | ast.AsyncFunctionDef):
                nome = filho.name
            if isinstance(filho, ast.keyword) and filho.arg in _KWARGS_DE_PROSA:
                continue
            if isinstance(filho, ast.JoinedStr) or (
                isinstance(filho, ast.Constant) and isinstance(filho.value, str)
            ):
                if id(filho) not in docstrings:
                    achados.append((nome, h._texto_logico(filho)))
                continue
            visita(filho, nome)

    visita(arv, "<modulo>")
    return achados


def _literais_que_casam(arquivos: list[Path], padrao: re.Pattern[str]) -> Counter[tuple[str, str]]:
    return Counter(
        (h.rel(a), fn)
        for a in arquivos
        for fn, texto in _literais_por_funcao(a)
        if padrao.search(texto)
    )


def _gaql_nas_tools() -> Counter[tuple[str, str]]:
    return _literais_que_casam(h.fontes_py(_TOOLS), _GAQL)


def _janela_fora_do_common() -> Counter[tuple[str, str]]:
    arquivos = [a for a in h.fontes_py(h.SRC) if a != _COMMON.resolve()]
    return _literais_que_casam(arquivos, _JANELA)


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


def test_gaql_so_fora_das_tools() -> None:
    novos = _excedentes(_gaql_nas_tools(), _GAQL_NAS_TOOLS)
    assert not novos, (
        f"GAQL (SELECT ... FROM) em src/mcp/tools acima do permitido, (medido, permitido): {novos}. "
        "Mova a consulta para src/google_ads/queries/; a allowlist so encolhe."
    )


def test_janela_so_no_common() -> None:
    novos = _excedentes(_janela_fora_do_common(), _JANELA_FORA_DO_COMMON)
    assert not novos, (
        f"`segments.date BETWEEN` fora de queries/_common.py acima do permitido, (medido, permitido): "
        f"{novos}. Use a janela canonica de _common.py; a allowlist so encolhe."
    )


def test_a_allowlist_de_gaql_descreve_a_realidade() -> None:
    folgas = _folgas(_gaql_nas_tools(), _GAQL_NAS_TOOLS)
    assert folgas == {}, f"ja consertado, encolha a allowlist, (medido, permitido): {folgas}"


def test_a_allowlist_de_janela_descreve_a_realidade() -> None:
    folgas = _folgas(_janela_fora_do_common(), _JANELA_FORA_DO_COMMON)
    assert folgas == {}, f"ja consertado, encolha a allowlist, (medido, permitido): {folgas}"
