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

SITIOS = [
    h.SRC / "mcp" / "tools" / "_meta_performance.py",
    h.SRC / "mcp" / "tools" / "meta_get_account_overview.py",
    h.SRC / "mcp" / "tools" / "meta_get_performance_breakdown.py",
]


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
