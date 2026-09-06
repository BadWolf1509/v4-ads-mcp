"""Testes do próprio harness.

Um harness de guards com bug é o mesmo defeito um nível acima: todo guard
construído sobre ele passa a mentir junto. Por isso cada scanner é exercitado
contra DOIS fixtures — um que contém a violação e um que não contém.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.unit import _guard_harness as h

FIXTURES = Path(__file__).resolve().parent / "fixtures_guards"


def test_fontes_py_e_recursivo_e_absoluto() -> None:
    achados = h.fontes_py(FIXTURES)
    assert achados, "fixture vazio invalida o teste"
    assert all(p.is_absolute() for p in achados)
    assert {p.name for p in achados} == {"modulo.py"}
    assert len({p.parent.name for p in achados}) == 2  # com_violacao E sem_violacao


def test_escopo_vazio_levanta_em_vez_de_passar() -> None:
    """A regra que mata a vacuidade.

    Medido em 2026-09-06: `Path("src/mcp/tools").glob("*.py")` devolve 74
    arquivos da raiz do repo e ZERO de qualquer outro cwd — e o guard do
    relógio passava verde varrendo nada.
    """
    vazio = FIXTURES / "diretorio_que_nao_existe"
    with pytest.raises(h.EscopoVazioError):
        h.fontes_py(vazio)


def test_fontes_py_ignora_pycache(tmp_path: Path) -> None:
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "lixo.py").write_text("x = 1", encoding="utf-8")
    (tmp_path / "real.py").write_text("y = 2", encoding="utf-8")
    assert [p.name for p in h.fontes_py(tmp_path)] == ["real.py"]


def test_fontes_py_resolve_raiz_relativa_para_absoluto(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Achado I2: uma raiz relativa não podia devolver paths relativos.

    Reproduz o padrão exato do guard do relógio que motivou esta task inteira
    (`Path("src/mcp/tools")`) — só que aqui, sem a correção, é este teste que
    falha em vez de um guard passar verde tendo varrido o cwd errado.
    """
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "modulo.py").write_text("x = 1", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    achados = h.fontes_py(Path("sub"))  # raiz RELATIVA — o ponto do teste

    assert achados
    assert all(p.is_absolute() for p in achados)
    assert achados == [(tmp_path.resolve() / "sub" / "modulo.py")]


def test_testes_py_e_recursivo_e_encontra_os_dois_fixtures() -> None:
    achados = h.testes_py(FIXTURES)
    assert achados, "fixture vazio invalida o teste"
    assert all(p.is_absolute() for p in achados)
    assert {p.name for p in achados} == {"modulo.py"}
    assert len({p.parent.name for p in achados}) == 2  # com_violacao E sem_violacao


def test_templates_html_default_encontra_template_real() -> None:
    """Caminho default (sem argumento) — ancora `TEMPLATES = SRC/web/templates`."""
    achados = h.templates_html()

    assert achados
    assert all(p.is_absolute() for p in achados)
    assert (h.TEMPLATES / "dashboard.html") in achados


def test_markdown_default_encontra_claude_md() -> None:
    """Caminho default (sem argumento) — ancora `RAIZ`, não só `SRC`."""
    achados = h.markdown()

    assert achados
    assert (h.RAIZ / "CLAUDE.md") in achados


def test_markdown_ignora_pytest_cache(tmp_path: Path) -> None:
    """Achado I1: `.pytest_cache/README.md` é criado pelo próprio pytest, no
    início da sessão — local e no CI. Sem a exclusão, `markdown()` sem
    argumento sempre incluía esse arquivo de terceiros, e `EscopoVazioError`
    não acusava nada porque a lista continuava não-vazia.
    """
    cache = tmp_path / ".pytest_cache"
    cache.mkdir()
    (cache / "README.md").write_text("gerado pelo pytest", encoding="utf-8")
    (tmp_path / "real.md").write_text("# real", encoding="utf-8")

    assert [p.name for p in h.markdown(tmp_path)] == ["real.md"]


def test_workflows_nao_recebe_raiz_e_ja_e_o_caminho_default() -> None:
    """`workflows()` não tem override de raiz — toda chamada já exercita o
    caminho default, sobre o `.github/workflows` real do repo."""
    achados = h.workflows()

    assert achados
    assert (h.RAIZ / ".github" / "workflows" / "ci.yml") in achados


def test_arvore_faz_parse_utf8_de_docstring_acentuada() -> None:
    modulo = h.arvore(FIXTURES / "sem_violacao" / "modulo.py")

    assert isinstance(modulo, ast.Module)
    nomes = {n.name for n in ast.walk(modulo) if isinstance(n, ast.FunctionDef)}
    assert "leitura_protegida" in nomes


def test_rel_devolve_barra_mesmo_no_windows() -> None:
    caminho = h.RAIZ / "tests" / "unit" / "_guard_harness.py"
    assert h.rel(caminho) == "tests/unit/_guard_harness.py"


def test_src_ancora_o_calculo_de_parents_2() -> None:
    """Achado I3: nada travava um off-by-one futuro em `parents[2]` — só
    apareceria muito depois, numa task posterior, longe da causa real.
    """
    assert h.SRC.name == "src"
    assert h.SRC.is_absolute()
    assert (h.SRC / "db" / "connection.py").is_file()
