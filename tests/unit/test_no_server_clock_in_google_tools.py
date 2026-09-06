"""F141 guard: tool Google nao le o relogio do servidor — `hoje` vem da conta.

A invariante e "um `hoje` por request, no fuso da conta". Antes do fix ela era
violada em TRES lugares dentro do mesmo caminho (`parse_date_range`, o clamp
F23 e a sonda de fronteira em `get_change_history`, mais o `LAST_2_DAYS` em
`detect_drift`), e o proximo `datetime.now(UTC).date()` que alguem escrever
num tool novo reabre a classe em silencio — o bug so aparece das 21h a
meia-noite locais, que e quando ninguem esta testando.

Por que AST e nao grep: comentarios e docstrings destes arquivos CITAM o
padrao proibido para explicar o fix (modo de falha 1 de guards-que-nao-cobrem:
o guard casa a propria prosa). O AST ve so chamadas.

Excecoes, cada uma com motivo — NAO e lista de alvos, e lista do que fica de
fora e por que:
- `meta_*` / `_meta_*`: contas Meta tem fuso proprio no inventario Meta; a
  mesma classe de bug la e outro finding, com outro fix.
- `get_my_rate_limit_status`: o bucket de quota E em UTC por desenho (mesma
  chave que `governance/rate_limit._today`); o campo se chama `date_utc`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.unit import _guard_harness as h

TOOLS = (
    h.SRC / "mcp" / "tools"
)  # absoluto, derivado de __file__ (harness); relativo via cwd zerava o glob
PRIMITIVOS = [
    h.SRC / "google_ads" / "queries" / "_common.py",
    h.SRC / "google_ads" / "change_freshness.py",
    # `account_clock.py` fica FORA desta lista de proposito: e o unico leitor
    # legitimo do relogio (como default injetavel), e tem teste proprio abaixo.
]
FORA_COM_MOTIVO = {
    # bucket de quota em UTC por desenho (mesma chave de governance/rate_limit)
    "get_my_rate_limit_status.py",
    # `datetime.now(_BRT)` numa checagem "conversao nao esta no futuro", com -03:00
    # HARDCODED — o tool inteiro assume BRT e anexa "-03:00" ao que envia ao
    # Google. Nao e predicado de janela (F141); e outra classe: contrato de upload
    # assumindo um fuso que 2 das 25 contas nao tem. Finding proprio (F146).
    "import_offline_conversions.py",
}


def _arquivos_google() -> list[Path]:
    return [
        p
        for p in h.fontes_py(TOOLS)
        if not p.name.startswith(("meta_", "_meta_")) and p.name not in FORA_COM_MOTIVO
    ] + PRIMITIVOS


def _chamadas_de_relogio(src: str) -> list[int]:
    """Linhas com `datetime.now(...)`, `date.today()` ou `datetime.today()` — so chamadas."""
    linhas: list[int] = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if (
            isinstance(f, ast.Attribute)
            and isinstance(f.value, ast.Name)
            and (f.value.id, f.attr)
            in {("datetime", "now"), ("date", "today"), ("datetime", "today")}
        ):
            linhas.append(node.lineno)
    return linhas


def test_nenhum_tool_google_le_o_relogio_do_servidor() -> None:
    ofensores = {
        str(p): _chamadas_de_relogio(p.read_text(encoding="utf-8")) for p in _arquivos_google()
    }
    ofensores = {k: v for k, v in ofensores.items() if v}
    assert ofensores == {}, (
        "relogio do servidor em caminho Google (F141) — `hoje` tem que vir de "
        f"`resolve_account_today`: {ofensores}"
    )


def test_account_clock_e_o_unico_que_le_o_relogio_e_so_como_default() -> None:
    """`resolve_account_today(now=None)` pode ler `datetime.now(UTC)` como default.

    E o UNICO lugar legitimo, e mesmo ali so como fallback injetavel. Se este
    teste falhar porque o modulo deixou de ler o relogio, tudo bem — ajuste o
    guard; se falhar porque outro modulo passou a ler, e o F141 voltando.
    """
    src = (h.SRC / "google_ads" / "account_clock.py").read_text(encoding="utf-8")
    assert _chamadas_de_relogio(src) == [] or "now if now is not None else datetime.now" in src


def test_o_guard_enxerga_uma_chamada_de_verdade() -> None:
    """Guard que nunca viu vermelho nao e guard: prova que o AST casa a forma proibida."""
    assert _chamadas_de_relogio("x = datetime.now(UTC).date()") == [1]
    assert _chamadas_de_relogio("# datetime.now(UTC).date() so no comentario") == []
    assert _chamadas_de_relogio('"""datetime.now(UTC) so na docstring"""') == []


def test_o_guard_do_relogio_recusa_escopo_vazio() -> None:
    """Antes do harness, `Path("src/mcp/tools")` relativo devolvia 0 arquivos de
    qualquer cwd que nao fosse a raiz, e o guard passava sem olhar nada."""
    import pytest

    with pytest.raises(h.EscopoVazioError):
        h.fontes_py(h.SRC / "mcp" / "tools" / "nao_existe")
