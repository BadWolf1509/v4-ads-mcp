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
