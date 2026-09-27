"""F197: o inventário de contas só é escrito pela reconciliação — os jobs.

`upsert_many` (Meta e Google) grava `is_active = true` e ZERA a série de ausências
(`missed_syncs`, `last_missed_on`). Fora da reconciliação, ele passa por cima da fonte
autoritativa (a parceria do BM, spec 2026-08-20; o MCC). Em 27/09 dois caminhos do painel o
chamavam a partir de `/me/adaccounts`: o botão "Sincronizar contas" (token do system user; 3
cliques em 21/09) e o callback do OAuth pessoal (token do gestor, aberto a qualquer gestor).
Cada chamada reiniciava a carência de conta saindo e reativava conta fora da parceria — e o
F154 tinha acabado de medir que esse índice nem prova alcance.

A invariante é "escritor único", não "ninguém chama `upsert_many`": `deactivate`,
`apply_absences`, `set_reachable` e `mark_inactive_except` também mudam o inventário. Por isso
os escritores são DERIVADOS do SQL de cada função dos dois repositórios (revisão do F197: a
primeira versão deste guard listava só `upsert_many`), e o SQL de escrita cru fora deles
também é barrado.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path

from tests.unit import _guard_harness as h

_REPOSITORIOS = {
    "src.db.repositories.meta_ad_accounts": h.SRC / "db" / "repositories" / "meta_ad_accounts.py",
    "src.db.repositories.google_ads_accounts": h.SRC
    / "db"
    / "repositories"
    / "google_ads_accounts.py",
}
_SQL_DE_ESCRITA = re.compile(
    r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(?:meta_ad_accounts|google_ads_accounts)\b",
    re.IGNORECASE,
)
_JOBS = h.SRC / "jobs"


def _sql_de_escrita(no: ast.AST, docstrings: set[int]) -> Iterator[ast.Constant]:
    """Literais de string (fora de docstring) que escrevem numa das duas tabelas."""
    for sub in ast.walk(no):
        if (
            isinstance(sub, ast.Constant)
            and isinstance(sub.value, str)
            and id(sub) not in docstrings
            and _SQL_DE_ESCRITA.search(sub.value)
        ):
            yield sub


def _escritores() -> frozenset[str]:
    achados: set[str] = set()
    for modulo, arquivo in _REPOSITORIOS.items():
        arv = h.arvore(arquivo)
        docstrings = h._nos_de_docstring(arv)
        for funcao in arv.body:
            if isinstance(funcao, ast.FunctionDef | ast.AsyncFunctionDef) and any(
                _sql_de_escrita(funcao, docstrings)
            ):
                achados.add(f"{modulo}.{funcao.name}")
    return frozenset(achados)


_ESCRITORES = _escritores()


def _chamadas_do_escritor(arv: ast.Module) -> list[int]:
    origens = h.origens_de_import(arv)
    return sorted(
        no.lineno
        for no in ast.walk(arv)
        if isinstance(no, ast.Call) and h.caminho_canonico(no.func, origens) in _ESCRITORES
    )


def _chamadas_no_arquivo(arquivo: Path) -> list[int]:
    return _chamadas_do_escritor(h.arvore(arquivo))


def test_so_os_jobs_escrevem_o_inventario() -> None:
    fora = {
        h.rel(arquivo): linhas
        for arquivo in h.fontes_py(h.SRC)
        if not arquivo.is_relative_to(_JOBS) and (linhas := _chamadas_no_arquivo(arquivo))
    }
    assert fora == {}, fora


def test_sql_que_escreve_o_inventario_so_mora_nos_dois_repositorios() -> None:
    """A outra porta: SQL cru num handler escreveria sem passar por função nenhuma."""
    repositorios = set(_REPOSITORIOS.values())
    fora = []
    for arquivo in h.fontes_py(h.SRC):
        if arquivo in repositorios:
            continue
        arv = h.arvore(arquivo)
        fora += [
            (h.rel(arquivo), no.lineno) for no in _sql_de_escrita(arv, h._nos_de_docstring(arv))
        ]
    assert fora == [], fora


def test_os_escritores_derivados_incluem_os_conhecidos() -> None:
    """Controle da derivação: se a regex ou a exclusão de docstring quebrassem, o conjunto
    encolheria em silêncio e os dois guards acima ficariam verdes olhando menos."""
    meta = "src.db.repositories.meta_ad_accounts"
    google = "src.db.repositories.google_ads_accounts"
    conhecidos = {
        f"{meta}.upsert_many",
        f"{meta}.apply_absences",
        f"{meta}.deactivate",
        f"{meta}.set_reachable",
        f"{google}.upsert_many",
        f"{google}.apply_absences",
        f"{google}.deactivate",
        f"{google}.mark_inactive_except",
    }
    assert conhecidos <= _ESCRITORES, conhecidos - _ESCRITORES
    assert not any(nome.rsplit(".", 1)[1].startswith(("get_", "list_")) for nome in _ESCRITORES)


def test_o_guard_enxerga_os_escritores_de_hoje() -> None:
    """Controle: a varredura acha a chamada dos dois jobs. Sem isto, um resolvedor que não
    casasse nada deixaria o guard acima verde para sempre."""
    achados = {h.rel(arquivo) for arquivo in h.fontes_py(_JOBS) if _chamadas_no_arquivo(arquivo)}
    assert achados == {"src/jobs/meta_resync.py", "src/jobs/account_resync.py"}


def test_o_guard_enxerga_as_duas_formas_de_import() -> None:
    """Os jobs só usam `modulo.funcao(...)`; o controle acima não prova a outra forma."""
    por_modulo = ast.parse(
        "from src.db.repositories import meta_ad_accounts\n"
        "async def f(conn):\n    await meta_ad_accounts.deactivate(conn, ad_account_ids=[])\n"
    )
    por_nome = ast.parse(
        "from src.db.repositories.google_ads_accounts import mark_inactive_except as m\n"
        "async def f(conn):\n    await m(conn, [])\n"
    )
    assert _chamadas_do_escritor(por_modulo) == [3]
    assert _chamadas_do_escritor(por_nome) == [3]


def test_nenhum_texto_manda_usar_o_caminho_que_saiu() -> None:
    """Consumidor em prosa: mensagens de erro e descriptions mandavam o gestor usar
    `meta_refresh_accounts` (nome de operação de audit, nunca uma tool) ou reconectar o
    OAuth para atualizar contas. Nenhum dos dois atualiza mais o inventário."""
    proibidos = ("meta_refresh_accounts", "refresh-accounts")
    achados = [
        (h.rel(arquivo), termo)
        for arquivo in [*h.fontes_py(h.SRC), *h.templates_html()]
        for termo in proibidos
        if termo in arquivo.read_text(encoding="utf-8")
    ]
    assert achados == [], achados
