"""As 5 tools Meta resolvem `hoje` pela conta, nao pelo relogio do servidor.

Guard de comportamento, complementando o guard estrutural (AST) do F141. O
estrutural diz "nao chame `datetime.now`"; este diz "o dia que sai da janela e
o da conta". Os dois juntos e que fecham: sem o AST, alguem reintroduz a
chamada num arquivo novo; sem este, alguem chama o resolvedor e joga fora o
resultado (a familia F112).
"""

from __future__ import annotations

import ast

import tests.unit._guard_harness as h

# D3: a resolucao vive em `resolver_janela_meta` (em `_meta_performance`). As tools que
# antes chamavam `resolve_meta_account_today` direto agora chamam o resolvedor de janela.
SITIO_DO_RELOGIO = h.SRC / "mcp" / "tools" / "_meta_performance.py"
CHAMADORES_DA_JANELA = [
    h.SRC / "mcp" / "tools" / "_meta_performance.py",
    h.SRC / "mcp" / "tools" / "meta_get_account_overview.py",
    h.SRC / "mcp" / "tools" / "meta_get_performance_breakdown.py",
]
SITIOS = [SITIO_DO_RELOGIO]


def _chama_resolvedor_de_janela(arv: ast.Module) -> bool:
    """`await resolver_janela_meta(...)` com o retorno amarrado a nomes (nao descartado)."""
    for n in ast.walk(arv):
        if not isinstance(n, ast.Assign):
            continue
        v = n.value
        if isinstance(v, ast.Await):
            v = v.value
        if (
            isinstance(v, ast.Call)
            and isinstance(v.func, ast.Name)
            and v.func.id == "resolver_janela_meta"
        ):
            return True
    return False


def _chama_o_resolvedor(arv: ast.Module) -> bool:
    return any(
        isinstance(n, ast.Call)
        and (
            (isinstance(n.func, ast.Name) and n.func.id == "resolve_meta_account_today")
            or (isinstance(n.func, ast.Attribute) and n.func.attr == "resolve_meta_account_today")
        )
        for n in ast.walk(arv)
    )


def _usa_o_retorno(arv: ast.Module) -> bool:
    """O resultado tem que ser AMARRADO a um nome — chamar e descartar e F112."""
    for n in ast.walk(arv):
        if not isinstance(n, ast.Assign):
            continue
        v = n.value
        if isinstance(v, ast.Await):
            v = v.value
        if isinstance(v, ast.Call) and (
            (isinstance(v.func, ast.Name) and v.func.id == "resolve_meta_account_today")
            or (isinstance(v.func, ast.Attribute) and v.func.attr == "resolve_meta_account_today")
        ):
            return True
    return False


def test_os_tres_sitios_resolvem_o_dia_pela_conta() -> None:
    faltando: list[str] = []
    for p in SITIOS:
        assert p.exists(), f"sitio sumiu do repo: {h.rel(p)} — atualize SITIOS"
        arv = h.arvore(p)
        if not _chama_o_resolvedor(arv):
            faltando.append(f"{h.rel(p)}: nao chama resolve_meta_account_today")
        elif not _usa_o_retorno(arv):
            faltando.append(f"{h.rel(p)}: chama e descarta o retorno (familia F112)")
    assert not faltando, (
        f"tools Meta ainda resolvem `hoje` sem a conta: {faltando}. "
        "Use `await resolve_meta_account_today(ad_account_id)` UMA vez por request "
        "e passe o mesmo `today` a tudo que precisa dele."
    )


def test_as_tres_tools_pegam_a_janela_do_resolvedor_unico() -> None:
    faltando = [
        h.rel(p) for p in CHAMADORES_DA_JANELA if not _chama_resolvedor_de_janela(h.arvore(p))
    ]
    assert not faltando, (
        f"tools Meta sem `await resolver_janela_meta(...)` amarrado: {faltando}. "
        "Janela e `hoje` saem de um lugar so, no fuso da conta."
    )
