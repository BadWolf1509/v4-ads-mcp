"""F197: o inventário de contas só é escrito pela reconciliação — os jobs.

`upsert_many` (Meta e Google) grava `is_active = true` e ZERA a série de ausências
(`missed_syncs`, `last_missed_on`). Fora da reconciliação, ele passa por cima da fonte
autoritativa (a parceria do BM, spec 2026-08-20; o MCC). Em 27/09 dois caminhos do painel o
chamavam a partir de `/me/adaccounts`: o botão "Sincronizar contas" (token do system user; 3
cliques em 21/09) e o callback do OAuth pessoal (token do gestor, aberto a qualquer gestor).
Cada chamada reiniciava a carência de conta saindo e reativava conta fora da parceria — e o
F154 tinha acabado de medir que esse índice nem prova alcance.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.unit import _guard_harness as h

_ESCRITORES = frozenset(
    {
        "src.db.repositories.meta_ad_accounts.upsert_many",
        "src.db.repositories.google_ads_accounts.upsert_many",
    }
)
_JOBS = h.SRC / "jobs"


def _chamadas_do_escritor(arquivo: Path) -> list[int]:
    arv = h.arvore(arquivo)
    origens = h.origens_de_import(arv)
    return sorted(
        no.lineno
        for no in ast.walk(arv)
        if isinstance(no, ast.Call) and h.caminho_canonico(no.func, origens) in _ESCRITORES
    )


def test_so_os_jobs_escrevem_o_inventario() -> None:
    fora = {
        h.rel(arquivo): linhas
        for arquivo in h.fontes_py(h.SRC)
        if not arquivo.is_relative_to(_JOBS) and (linhas := _chamadas_do_escritor(arquivo))
    }
    assert fora == {}, fora


def test_o_guard_enxerga_os_escritores_de_hoje() -> None:
    """Controle: a varredura acha a chamada dos dois jobs. Sem isto, um resolvedor que não
    casasse nada deixaria o guard acima verde para sempre."""
    achados = {h.rel(arquivo) for arquivo in h.fontes_py(_JOBS) if _chamadas_do_escritor(arquivo)}
    assert achados == {"src/jobs/meta_resync.py", "src/jobs/account_resync.py"}


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
