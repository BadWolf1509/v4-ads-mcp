"""Ratchets de camada: SQL nas rotas, `create_pending`, GAQL nas tools e janela de data.

Quatro acoplamentos que a arquitetura em camadas proíbe e que o código já tem em
resíduo conhecido:

1. Rota do painel (`src/web/routes/*.py`) fala com o banco por função de
   repositório; chamar `fetch`/`fetchrow`/`fetchval`/`execute`/`executemany`
   direto na rota espalha SQL pela camada HTTP.
2. Tool de mutação cria a confirmação pendente pelo helper de preview
   (`_mutate_common.py`); chamar `create_pending` por conta própria duplica o
   envelope e deixa a tool escapar das garantias do helper.
3. GAQL fica na camada de queries (`src/google_ads/queries/`, `preflight.py`):
   tool que escreve `SELECT ... FROM <recurso>` por conta própria espalha
   consulta pela camada MCP (4 tools hoje).
4. A janela de data (`segments.date BETWEEN`) tem definição única em
   `queries/_common.py`; reescrevê-la à mão é como nasce a janela divergente.

Cada resíduo é uma allowlist que SÓ ENCOLHE. Quem a encolhe, no plano de 10/11:
D3 migra 3 das 5 tools de `create_pending` (as outras 2 ficam); C2 esvazia a de
janela; I3 esvazia a de GAQL; G2 esvazia a de SQL nas rotas. A chave é
`(arquivo, função)`, nunca a linha, para a allowlist não quebrar a cada edição.
Cada chave guarda o NÚMERO de ocorrências: função já listada que ganha mais uma
falha, e limpeza parcial (menos do que o permitido) obriga a encolher a
contagem. O teste de "descreve a realidade" impede o ratchet de apodrecer:
entrada que já foi consertada tem que sair da lista.

Allowlist vazia não prova nada sozinha: o scanner pode ter quebrado e devolver
zero. Por isso cada detector tem controles sintéticos, positivos e negativos,
passados pela MESMA função que varre `src/` (`test_detector_*`).
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.unit import _guard_harness as h

_ROTAS = h.SRC / "web" / "routes"
_TOOLS = h.SRC / "mcp" / "tools"

_METODOS_DE_BANCO = frozenset({"fetch", "fetchrow", "fetchval", "execute", "executemany"})

# (arquivo relativo à raiz, função de topo que contém a chamada).
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

# (arquivo, função) -> número de chamadas a `create_pending` fora de `_mutate_common.py`.
_CREATE_PENDING_FORA_DO_HELPER: dict[tuple[str, str], int] = {
    ("src/mcp/tools/bulk_pause_by_query.py", "bulk_pause_by_query"): 1,
    ("src/mcp/tools/update_keyword_status.py", "update_keyword_status"): 1,
}

# (arquivo, função) -> número de textos GAQL (`SELECT ... FROM <recurso>`) nas tools.
_GAQL_NAS_TOOLS: dict[tuple[str, str], int] = {
    ("src/mcp/tools/apply_audience.py", "_validate_user_interest_taxonomies"): 1,
    ("src/mcp/tools/update_ad_group_bid.py", "update_ad_group_bid"): 1,
    ("src/mcp/tools/update_campaign_budget.py", "update_campaign_budget"): 1,
    ("src/mcp/tools/update_keyword_bid.py", "update_keyword_bid"): 1,
}

# (arquivo, função) -> número de textos com `segments.date BETWEEN` fora de `_common.py`.
_JANELA_FORA_DO_COMMON: dict[tuple[str, str], int] = {}

_COMMON = h.SRC / "google_ads" / "queries" / "_common.py"
# "Texto GAQL" = o texto lógico de uma EXPRESSÃO de string (literais, f-strings,
# concatenação implícita e cadeias de `+`; o `{expr}` e o operando não-literal
# viram `X`; `.format()` tem receptor literal e conta como está) que COMEÇA com
# `select` (qualquer caixa) e contém `from` como palavra. Prosa que apenas
# MENCIONA SELECT/FROM não começa com SELECT, então não precisa de exceção por
# nome de keyword.
_GAQL = re.compile(r"\s*select\b(?=.*\bfrom\b)", re.DOTALL | re.IGNORECASE)
_JANELA = re.compile(r"segments\.date\s+between", re.IGNORECASE)


def _folhas_de_soma(no: ast.expr) -> list[ast.expr]:
    """Operandos de uma cadeia `a + b + c`, na ordem."""
    if isinstance(no, ast.BinOp) and isinstance(no.op, ast.Add):
        return [*_folhas_de_soma(no.left), *_folhas_de_soma(no.right)]
    return [no]


def _e_literal_de_string(no: ast.AST) -> bool:
    return isinstance(no, ast.JoinedStr) or (
        isinstance(no, ast.Constant) and isinstance(no.value, str)
    )


def _literais_por_funcao(
    arv: ast.Module, *, pular_description: bool = False
) -> list[tuple[str, str]]:
    """`(função mais externa, texto lógico)` de cada expressão de string.

    Fora: docstring. Cadeia `+` com ao menos um literal de string vira UM texto
    (operando não-literal -> `X`); adjacentes e f-strings já chegam fundidos pelo
    parser. `pular_description` (só o scan de janela): ignora o valor de
    `description=` de uma chamada, texto de tool que cita `segments.date BETWEEN`
    sem ser query.
    """
    docstrings = h._nos_de_docstring(arv)
    achados: list[tuple[str, str]] = []

    def visita(no: ast.AST, externa: str) -> None:
        for filho in ast.iter_child_nodes(no):
            nome = externa
            if externa == "<modulo>" and isinstance(filho, ast.FunctionDef | ast.AsyncFunctionDef):
                nome = filho.name
            if pular_description and isinstance(filho, ast.keyword) and filho.arg == "description":
                continue
            if isinstance(filho, ast.BinOp) and isinstance(filho.op, ast.Add):
                folhas = _folhas_de_soma(filho)
                if any(_e_literal_de_string(f) for f in folhas):
                    partes = [
                        h._texto_logico(f)  # type: ignore[arg-type]
                        if _e_literal_de_string(f)
                        else "X"
                        for f in folhas
                    ]
                    achados.append((nome, "".join(partes)))
                    for f in folhas:  # operando não-literal pode ter outra expressão
                        if not _e_literal_de_string(f):
                            visita(ast.Expression(body=f), nome)
                    continue
            if _e_literal_de_string(filho):
                if id(filho) not in docstrings:
                    achados.append((nome, h._texto_logico(filho)))  # type: ignore[arg-type]
                continue
            visita(filho, nome)

    visita(arv, "<modulo>")
    return achados


def _sitios(arv: ast.Module, casa: Callable[[ast.Call], bool]) -> list[tuple[str, int]]:
    """`(função mais externa, linha)` de cada chamada que `casa(call)` aceita.

    A função é a MAIS EXTERNA (de topo, ou o método da classe): lambda e função
    aninhada são atribuídas a ela, porque a rota é a unidade que o ratchet
    cobra e `lambda c: c.fetch(...)` é SQL direto da mesma rota. Chamada em
    nível de módulo vira `<modulo>`.
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

    visita(arv, "<modulo>")
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


# Detectores por árvore: o que o ratchet conta em `src/` e o que os controles
# sintéticos exercitam é a MESMA função. Cada um devolve a função mais externa
# de cada ocorrência.
def _sql_na_arvore(arv: ast.Module) -> list[str]:
    return [fn for fn, _ in _sitios(arv, _e_sql)]


def _create_pending_na_arvore(arv: ast.Module) -> list[str]:
    nomes = frozenset(h.nomes_locais(arv, "create_pending"))
    return [fn for fn, _ in _sitios(arv, _e_create_pending(nomes))]


def _gaql_na_arvore(arv: ast.Module) -> list[str]:
    return [fn for fn, texto in _literais_por_funcao(arv) if _GAQL.match(texto)]


def _janela_na_arvore(arv: ast.Module) -> list[str]:
    return [
        fn
        for fn, texto in _literais_por_funcao(arv, pular_description=True)
        if _JANELA.search(texto)
    ]


def _contar(
    arquivos: list[Path], detector: Callable[[ast.Module], list[str]]
) -> Counter[tuple[str, str]]:
    return Counter((h.rel(a), fn) for a in arquivos for fn in detector(h.arvore(a)))


def _sql_em_rotas() -> Counter[tuple[str, str]]:
    return _contar(h.fontes_py(_ROTAS), _sql_na_arvore)


def _create_pending_fora() -> Counter[tuple[str, str]]:
    arquivos = [a for a in h.fontes_py(_TOOLS) if a.name != "_mutate_common.py"]
    return _contar(arquivos, _create_pending_na_arvore)


def _gaql_nas_tools() -> Counter[tuple[str, str]]:
    return _contar(h.fontes_py(_TOOLS), _gaql_na_arvore)


def _janela_fora_do_common() -> Counter[tuple[str, str]]:
    arquivos = [a for a in h.fontes_py(h.SRC) if a != _COMMON.resolve()]
    return _contar(arquivos, _janela_na_arvore)


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


# Nome da allowlist -> (allowlist, medição). O nome vai na mensagem de falha: é o
# dict que quem leu a falha tem de editar.
_RATCHETS: dict[str, tuple[dict[tuple[str, str], int], Callable[[], Counter[tuple[str, str]]]]] = {
    "_SQL_EM_ROTA_CONHECIDO": (_SQL_EM_ROTA_CONHECIDO, _sql_em_rotas),
    "_CREATE_PENDING_FORA_DO_HELPER": (_CREATE_PENDING_FORA_DO_HELPER, _create_pending_fora),
    "_GAQL_NAS_TOOLS": (_GAQL_NAS_TOOLS, _gaql_nas_tools),
    "_JANELA_FORA_DO_COMMON": (_JANELA_FORA_DO_COMMON, _janela_fora_do_common),
}


def test_rota_nao_chama_conn_direto() -> None:
    novos = _excedentes(_sql_em_rotas(), _SQL_EM_ROTA_CONHECIDO)
    assert not novos, (
        "rota do painel com SQL direto (fetch/fetchrow/fetchval/execute/"
        f"executemany em qualquer receptor) acima do permitido, (medido, permitido): {novos}. "
        "Mova a consulta para uma função de repositório; _SQL_EM_ROTA_CONHECIDO só encolhe."
    )


def test_create_pending_so_no_helper() -> None:
    novos = _excedentes(_create_pending_fora(), _CREATE_PENDING_FORA_DO_HELPER)
    assert not novos, (
        f"create_pending fora de _mutate_common.py acima do permitido, (medido, permitido): {novos}. "
        "Use o helper de preview; _CREATE_PENDING_FORA_DO_HELPER só encolhe."
    )


def test_gaql_so_fora_das_tools() -> None:
    novos = _excedentes(_gaql_nas_tools(), _GAQL_NAS_TOOLS)
    assert not novos, (
        f"GAQL (SELECT ... FROM) em src/mcp/tools acima do permitido, (medido, permitido): {novos}. "
        "Mova a consulta para src/google_ads/queries/; _GAQL_NAS_TOOLS só encolhe."
    )


def test_janela_so_no_common() -> None:
    novos = _excedentes(_janela_fora_do_common(), _JANELA_FORA_DO_COMMON)
    assert not novos, (
        f"`segments.date BETWEEN` fora de queries/_common.py acima do permitido, (medido, permitido): "
        f"{novos}. Use a janela canônica de _common.py; _JANELA_FORA_DO_COMMON só encolhe."
    )


@pytest.mark.parametrize("nome", list(_RATCHETS))
def test_a_allowlist_descreve_a_realidade(nome: str) -> None:
    permitido, medir = _RATCHETS[nome]
    folgas = _folgas(medir(), permitido)
    assert folgas == {}, (
        f"já consertado: encolha {nome} em tests/unit/test_ratchet_camadas.py "
        f"(tire a chave ou baixe a contagem), (medido, permitido): {folgas}"
    )


@pytest.mark.parametrize("nome", list(_RATCHETS))
def test_contagens_permitidas_sao_positivas(nome: str) -> None:
    """Chave com contagem 0 passa calada nos dois testes: tem que sair do dict."""
    permitido, _ = _RATCHETS[nome]
    nao_positivas = {k: n for k, n in permitido.items() if n < 1}
    assert nao_positivas == {}, (
        f"{nome} tem contagem < 1 (tire a chave em vez de zerar): {nao_positivas}"
    )


# Controles sintéticos: (ident, detector, fonte, funções esperadas). Positivo = a
# lista não vazia, com a função a quem o ratchet cobraria; negativo = [].
_DETECTORES: dict[str, Callable[[ast.Module], list[str]]] = {
    "sql": _sql_na_arvore,
    "create_pending": _create_pending_na_arvore,
    "gaql": _gaql_na_arvore,
    "janela": _janela_na_arvore,
}

_CONTROLES: list[tuple[str, str, str, list[str]]] = [
    # SQL direto na rota: qualquer receptor, inclusive dentro de lambda aninhada.
    ("sql_conn_fetch", "sql", 'async def r(conn):\n    await conn.fetch("SELECT 1")', ["r"]),
    ("sql_pool_execute", "sql", 'async def r(pool):\n    await pool.execute("x")', ["r"]),
    (
        "sql_fetch_em_lambda_aninhada",
        "sql",
        'async def r(pool):\n    return await com(pool, lambda c: c.fetchrow("x"))',
        ["r"],
    ),
    ("sql_metodo_de_repositorio", "sql", "async def r(conn):\n    await repo.listar(conn)", []),
    ("sql_funcao_solta_fetch", "sql", "async def r(conn):\n    await fetch(conn)", []),
    # create_pending: direto, por atributo e por alias de import.
    (
        "create_pending_direto",
        "create_pending",
        "async def t(conn):\n    await create_pending(conn, p)",
        ["t"],
    ),
    (
        "create_pending_alias_cp",
        "create_pending",
        "from src.db.repositories.pending import create_pending as cp\n"
        "async def t(conn):\n    await cp(conn, p)",
        ["t"],
    ),
    (
        "create_pending_por_atributo",
        "create_pending",
        "async def t(conn):\n    await pending.create_pending(conn, p)",
        ["t"],
    ),
    (
        "create_pending_helper",
        "create_pending",
        "async def t(conn):\n    await emitir_preview(conn, p)",
        [],
    ),
    ("create_pending_cp_sem_alias", "create_pending", "async def t(c):\n    await cp(c)", []),
    # GAQL: f-string, cadeia `+`, minúsculas, `.format`.
    ("gaql_fstring", "gaql", 'def t(x):\n    q = f"SELECT a FROM {x} WHERE b = 1"', ["t"]),
    ("gaql_cadeia_soma", "gaql", 'def t(c):\n    q = "SELECT " + c + " FROM ad_group"', ["t"]),
    ("gaql_minusculas", "gaql", 'def t():\n    q = "select a.b from campaign"', ["t"]),
    ("gaql_format", "gaql", 'def t(r):\n    q = "SELECT a FROM {}".format(r)', ["t"]),
    (
        "gaql_docstring",
        "gaql",
        # Começa com SELECT de propósito: só o filtro de docstring a separa da query.
        'def t():\n    """SELECT ... FROM campaign: o que esta função monta."""\n    return 1',
        [],
    ),
    ("gaql_prosa", "gaql", 'def t():\n    m = "use SELECT para listar campos"', []),
    (
        "gaql_prosa_que_cita_select_from",
        "gaql",
        'def t():\n    m = "a GAQL precisa de SELECT e FROM"',
        [],
    ),
    # Janela: quebra de linha dentro do texto e `BETWEEN` partido por `+`.
    (
        "janela_quebra_de_linha",
        "janela",
        'def b(a, z):\n    w = f"""WHERE segments.date\nBETWEEN \'{a}\' AND \'{z}\'"""',
        ["b"],
    ),
    (
        "janela_partida_por_soma",
        "janela",
        'def b(a):\n    w = "WHERE segments.date " + "BETWEEN " + a',
        ["b"],
    ),
    (
        "janela_em_description",
        "janela",
        'registrar(nome="t", description="filtra por segments.date BETWEEN a e b")',
        [],
    ),
    (
        "janela_docstring",
        "janela",
        'def b():\n    """Monta segments.date BETWEEN a partir das datas."""\n    return 1',
        [],
    ),
]


@pytest.mark.parametrize(
    ("detector", "fonte", "esperado"),
    [(d, f, e) for _, d, f, e in _CONTROLES],
    ids=[ident for ident, _, _, _ in _CONTROLES],
)
def test_detector_acusa_a_violacao_e_so_ela(detector: str, fonte: str, esperado: list[str]) -> None:
    """Contrato de cada scanner, pela MESMA função que varre `src/`.

    Sem isto, uma allowlist esvaziada por C2/D3/G2/I3 deixaria o teste
    bloqueante passando com um scanner que nunca acusa nada.
    """
    obtido = _DETECTORES[detector](ast.parse(fonte))
    assert obtido == esperado, (
        f"detector {detector!r}: esperado {esperado or 'passa'}, obtido {obtido or 'passa'} "
        f"para:\n{fonte}"
    )


def test_controles_cobrem_positivo_e_negativo_de_cada_detector() -> None:
    for nome in _DETECTORES:
        vereditos = {bool(e) for _, d, _, e in _CONTROLES if d == nome}
        assert vereditos == {True, False}, f"detector {nome!r} sem positivo e negativo"
