"""`src.auth.token_assinado` é privado de `oauth_state` e `panel_session`.

`assinar`/`verificar` aceitam a união `Audience` (state ∪ painel): quem os importa
consegue cunhar token de QUALQUER audiência e o mypy aprova. A separação
`StateAudience` × `PanelAudience` só vale se o codec ficar atrás dos dois wrappers
tipados. Este guard varre `src/` por AST e falha se outro módulo o importar, em
qualquer forma (`import`, `from ... import`, relativo, `from src.auth import`).
Teste pode importá-lo: a varredura é só de `src/`.
"""

from __future__ import annotations

import ast

import tests.unit._guard_harness as h

_ALVO = "src.auth.token_assinado"
_PERMITIDOS = {"src/auth/oauth_state.py", "src/auth/panel_session.py"}


def linhas_que_importam_o_codec(arv: ast.Module, pacote: list[str]) -> list[int]:
    """Linhas de `arv` que importam o codec; `pacote` = partes do pacote do arquivo."""
    linhas: list[int] = []
    for no in ast.walk(arv):
        nomes: list[str] = []
        if isinstance(no, ast.Import):
            nomes = [a.name for a in no.names]
        elif isinstance(no, ast.ImportFrom):
            base = no.module or ""
            if no.level:
                ancora = pacote[: len(pacote) - (no.level - 1)]
                base = ".".join([*ancora, *([no.module] if no.module else [])])
            nomes = [base, *(f"{base}.{a.name}" for a in no.names)]
        if any(n == _ALVO or n.startswith(_ALVO + ".") for n in nomes):
            linhas.append(no.lineno)
    return linhas


def test_so_oauth_state_e_panel_session_importam_o_codec() -> None:
    achados: dict[str, list[int]] = {}
    for arq in h.fontes_py():
        pacote = list(arq.relative_to(h.RAIZ).with_suffix("").parts[:-1])
        linhas = linhas_que_importam_o_codec(h.arvore(arq), pacote)
        if linhas:
            achados[h.rel(arq)] = linhas
    # Piso de vacuidade: os dois importadores legítimos têm de ser vistos.
    faltando = sorted(_PERMITIDOS - set(achados))
    assert not faltando, f"o scanner nao viu os importadores legitimos {faltando}"
    intrusos = {a: ls for a, ls in achados.items() if a not in _PERMITIDOS}
    assert not intrusos, (
        "token_assinado e privado de oauth_state/panel_session (cunhar token de audiencia "
        f"arbitraria quebra StateAudience x PanelAudience): {intrusos}"
    )


def test_o_scanner_pega_cada_forma_de_import() -> None:
    """Autoteste: cada forma de import, como se o arquivo morasse em src/auth/."""
    pacote = ["src", "auth"]
    for linha in (
        "import src.auth.token_assinado",
        "from src.auth.token_assinado import assinar",
        "from .token_assinado import assinar",
        "from src.auth import token_assinado",
        "from . import token_assinado",
    ):
        assert linhas_que_importam_o_codec(ast.parse(linha), pacote) == [1], linha
    assert not linhas_que_importam_o_codec(ast.parse("from src.auth import oauth_state"), pacote)


# --- O reexport (follow-up da Parte H, 11/11) ------------------------------------
# `oauth_state` e `panel_session` importam `assinar`/`verificar` do codec, entao os
# dois nomes viram ATRIBUTOS desses modulos: `from src.auth.oauth_state import
# assinar` cunha token de audiencia arbitraria e o guard acima nao via — ele so
# olha quem importa o CODEC. Os nomes reexportados sao derivados do AST dos dois
# wrappers (nao listados a mao): codec que ganhar funcao nova entra sozinho.
_WRAPPERS = {"src.auth.oauth_state": "src/auth/oauth_state.py",
             "src.auth.panel_session": "src/auth/panel_session.py"}  # fmt: skip


def caminhos_reexportados() -> set[str]:
    caminhos: set[str] = set()
    for modulo, arquivo in _WRAPPERS.items():
        for no in ast.walk(h.arvore(h.RAIZ / arquivo)):
            if isinstance(no, ast.ImportFrom) and no.module == _ALVO:
                caminhos |= {f"{modulo}.{a.asname or a.name}" for a in no.names}
    return caminhos


def _modulo_absoluto(no: ast.ImportFrom, pacote: list[str]) -> str | None:
    """`from .x import y` resolvido contra o pacote do arquivo (11/11, revisao do #240).

    Antes o scanner pulava todo `ImportFrom` com `level`: `from .oauth_state import
    assinar` dentro de `src/auth/` passava. O harness diz que `src/` nao tem import
    relativo, mas nada aplica isso — o guard nao pode depender da convencao.
    """
    if not no.level:
        return no.module
    if no.level - 1 > len(pacote):
        return None
    ancora = pacote[: len(pacote) - (no.level - 1)]
    return ".".join([*ancora, *([no.module] if no.module else [])])


def usos_do_reexport(
    arv: ast.Module, proibidos: set[str], pacote: list[str] | None = None
) -> list[int]:
    """Linhas que chegam a um nome do codec PELO wrapper, em qualquer forma estatica.

    Fora, como limitacao declarada (despacho dinamico vence qualquer varredura
    sintatica): `getattr(modulo, nome_variavel)`, `importlib.import_module(...)`,
    `vars(modulo)[...]`, `sys.modules[...]` e `from ... import *`. O mypy strict com
    `no_implicit_reexport` cobre as formas diretas por outro caminho.
    """
    origens = h.origens_de_import(arv)
    linhas: list[int] = []
    for no in ast.walk(arv):
        if isinstance(no, ast.ImportFrom):
            modulo = _modulo_absoluto(no, pacote or [])
            if modulo and any(f"{modulo}.{a.name}" in proibidos for a in no.names):
                linhas.append(no.lineno)
        elif (
            isinstance(no, ast.Attribute | ast.Name)
            and h.caminho_canonico(no, origens) in proibidos
        ):
            linhas.append(no.lineno)
    return sorted(set(linhas))


def test_ninguem_usa_o_codec_pelo_reexport_dos_wrappers() -> None:
    proibidos = caminhos_reexportados()
    assert {"src.auth.oauth_state.assinar", "src.auth.panel_session.verificar"} <= proibidos
    achados = {
        h.rel(arq): ls
        for arq in h.fontes_py()
        if h.rel(arq) not in _PERMITIDOS
        and (
            ls := usos_do_reexport(
                h.arvore(arq),
                proibidos,
                list(arq.relative_to(h.RAIZ).with_suffix("").parts[:-1]),
            )
        )
    }
    assert not achados, f"codec usado pelo reexport de oauth_state/panel_session: {achados}"


def test_o_scanner_do_reexport_pega_cada_forma() -> None:
    """Autoteste: o guard antigo devolvia [] para todas estas (medido em 11/11)."""
    proibidos = caminhos_reexportados()
    for trecho in (
        "from src.auth.oauth_state import assinar",
        "from src.auth.panel_session import verificar as v",
        "from src.auth import oauth_state\noauth_state.assinar(1)",
        "import src.auth.panel_session\nsrc.auth.panel_session.assinar(1)",
        "import src.auth.oauth_state as o\no.verificar(1)",
    ):
        arv = ast.parse(trecho)
        assert usos_do_reexport(arv, proibidos), trecho
        assert not linhas_que_importam_o_codec(arv, ["src", "auth"]), trecho
    for limpo in (
        "from src.auth.oauth_state import sign_state",
        "from src.auth import oauth_state\noauth_state.sign_state(1)",
    ):
        assert not usos_do_reexport(ast.parse(limpo), proibidos), limpo


def test_o_scanner_do_reexport_pega_o_import_relativo() -> None:
    """Como se o arquivo morasse em `src/auth/`: o scanner antigo devolvia [] aqui."""
    proibidos = caminhos_reexportados()
    for trecho in (
        "from .oauth_state import assinar",
        "from .panel_session import verificar as v",
        "from ..auth.oauth_state import assinar",
    ):
        assert usos_do_reexport(ast.parse(trecho), proibidos, ["src", "auth"]), trecho
    assert not usos_do_reexport(
        ast.parse("from .oauth_state import sign_state"), proibidos, ["src", "auth"]
    )
