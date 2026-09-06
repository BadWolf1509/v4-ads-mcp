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


def test_coletar_centraliza_resolve_para_funcao_de_escopo_nova(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Achado A (rodada 2): `.resolve()` sai das 4 funções e passa a morar só
    em `_coletar`.

    Prova que a centralização vale para uma função de escopo que AINDA NÃO
    EXISTE, não só para as 4 atuais: a função abaixo é definida aqui dentro
    do teste, chama `_coletar` diretamente e não chama `.resolve()` em lugar
    nenhum — exatamente como uma task futura escreveria por engano se
    reproduzisse o padrão do bug original (`Path("src/mcp/tools")` relativo).
    Se a garantia dependesse de copiar `.resolve()` em cada call-site em vez
    de morar dentro de `_coletar`, este teste falharia; ele só passa porque
    `_coletar` resolve por conta própria.
    """

    def scanner_hipotetico(raiz: Path) -> list[Path]:
        return h._coletar(raiz.rglob("*.txt"), raiz=raiz, padrao="*.txt")

    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "arquivo.txt").write_text("x", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    achados = scanner_hipotetico(Path("sub"))  # raiz RELATIVA, sem .resolve() no chamador

    assert achados
    assert all(p.is_absolute() for p in achados)
    assert achados == [(tmp_path.resolve() / "sub" / "arquivo.txt")]


def test_fontes_py_default_usa_src() -> None:
    """Caminho default (sem argumento) — ancora `SRC`, nunca exercitado por
    uma chamada de verdade a `fontes_py()` (achado da rodada 2 de revisão).
    """
    achados = h.fontes_py()

    assert achados
    assert all(p.is_absolute() for p in achados)
    assert (h.SRC / "db" / "connection.py") in achados


def test_testes_py_e_recursivo_e_encontra_os_dois_fixtures() -> None:
    achados = h.testes_py(FIXTURES)
    assert achados, "fixture vazio invalida o teste"
    assert all(p.is_absolute() for p in achados)
    assert {p.name for p in achados} == {"modulo.py"}
    assert len({p.parent.name for p in achados}) == 2  # com_violacao E sem_violacao


def test_testes_py_default_usa_tests() -> None:
    """Caminho default (sem argumento) — ancora `TESTES`, nunca exercitado
    por uma chamada de verdade a `testes_py()` (achado da rodada 2 de
    revisão)."""
    achados = h.testes_py()

    assert achados
    assert all(p.is_absolute() for p in achados)
    assert (h.TESTES / "unit" / "_guard_harness.py") in achados


def test_templates_html_default_encontra_template_real() -> None:
    """Caminho default (sem argumento) — ancora `TEMPLATES = SRC/web/templates`."""
    achados = h.templates_html()

    assert achados
    assert all(p.is_absolute() for p in achados)
    assert (h.TEMPLATES / "dashboard.html") in achados


def test_templates_html_ignora_node_modules(tmp_path: Path) -> None:
    """Par sintético que faltava (achado da rodada 2): só havia call-site
    contra arquivo real, sem nenhum caso que `templates_html` deva EXCLUIR.
    `node_modules` já está em `_IGNORADOS` — sem a exclusão aplicada aqui
    também, um `.html` vendorizado apareceria como se fosse template da
    aplicação.
    """
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "vendor.html").write_text("x", encoding="utf-8")
    (tmp_path / "pagina.html").write_text("y", encoding="utf-8")

    assert [p.name for p in h.templates_html(tmp_path)] == ["pagina.html"]


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


def test_workflows_default_encontra_ci_yml() -> None:
    """Caminho default (sem argumento) — ancora `.github/workflows` real.

    Achado A (rodada 2): `workflows()` ganhou `raiz` opcional, igual às
    outras 4 funções de escopo do módulo — nome e docstring antigos ("não
    recebe raiz") descreviam a assinatura anterior, já substituída.
    """
    achados = h.workflows()

    assert achados
    assert (h.RAIZ / ".github" / "workflows" / "ci.yml") in achados


def test_workflows_ignora_diretorio_ignorado(tmp_path: Path) -> None:
    """Par sintético que faltava (achado da rodada 2): só havia call-site
    contra arquivo real, sem nenhum caso que `workflows` deva EXCLUIR.

    `workflows()` não é recursivo (workflow do GitHub Actions não aninha em
    subdiretório) — por isso um `.yml` DENTRO de um subdiretório ignorado de
    `raiz` já ficaria de fora só pelo `.glob()` não descer, sem provar nada
    sobre `_IGNORADOS` (tentei essa forma primeiro; o teste passava mesmo com
    `_IGNORADOS` vazio — não mordia). A forma que realmente exercita o filtro
    compartilhado é a própria `raiz` caindo dentro de um diretório ignorado:
    aí o único `.yml` (que o `.glob()` encontra, top-level, de verdade) é
    excluído por `_IGNORADOS`, e `_coletar` acusa escopo vazio.
    """
    ignorado = tmp_path / ".venv" / "workflows"
    ignorado.mkdir(parents=True)
    (ignorado / "fantasma.yml").write_text("x", encoding="utf-8")

    with pytest.raises(h.EscopoVazioError):
        h.workflows(ignorado)


def test_arvore_faz_parse_utf8_de_docstring_acentuada() -> None:
    modulo = h.arvore(FIXTURES / "sem_violacao" / "modulo.py")

    assert isinstance(modulo, ast.Module)
    nomes = {n.name for n in ast.walk(modulo) if isinstance(n, ast.FunctionDef)}
    assert "leitura_protegida" in nomes


def test_arvore_faz_parse_do_fixture_com_violacao() -> None:
    """`arvore` só era exercitada contra `sem_violacao` (achado da rodada 2):
    dá o par, provando que o parser não é hardcoded para uma única árvore.
    """
    modulo = h.arvore(FIXTURES / "com_violacao" / "modulo.py")

    assert isinstance(modulo, ast.Module)
    nomes = {n.name for n in ast.walk(modulo) if isinstance(n, ast.FunctionDef)}
    assert nomes == {"repete_a_tupla_literal", "usa_alias_de_import", "chama_por_alias"}


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


def _arv(src: str) -> ast.Module:
    return ast.parse(src)


def test_chama_resolve_name_attribute_e_alias() -> None:
    direto = _arv("from m import alvo\ndef f():\n    alvo()\n")
    atributo = _arv("import m\ndef f():\n    m.alvo()\n")
    apelidado = _arv("from m import alvo as outro\ndef f():\n    outro()\n")
    for arv in (direto, atributo, apelidado):
        assert h.chama(arv, "alvo", arv=arv), ast.dump(arv)[:60]

    nao_chama = _arv("def f():\n    alvo_parecido()\n")
    assert not h.chama(nao_chama, "alvo", arv=nao_chama)


def test_funcoes_inclui_aninhada_metodo_e_async() -> None:
    arv = _arv(
        "def topo():\n"
        "    def aninhada():\n        pass\n"
        "class C:\n"
        "    async def metodo(self):\n        pass\n"
    )
    assert {f.name for f in h.funcoes(arv)} == {"topo", "aninhada", "metodo"}


def test_classe_de_excecao_resolve_builtin_e_asyncpg() -> None:
    import asyncpg

    assert h.classe_de_excecao("ConnectionResetError") is ConnectionResetError
    assert h.classe_de_excecao("asyncpg.ConnectionDoesNotExistError") is (
        asyncpg.ConnectionDoesNotExistError
    )
    assert h.classe_de_excecao("NaoExisteEmLugarNenhum") is None


def test_subclasse_e_o_que_importa_nao_o_nome() -> None:
    """A propriedade que o guard do F91 falhou em afirmar.

    Medido em 2026-09-06: as 4 grafias abaixo passavam verdes pelo guard, e as
    4 são subclasses reais do que `run_with_reconnect` retenta.
    """
    import asyncpg

    retentaveis = (asyncpg.PostgresConnectionError, ConnectionError)
    for grafia in (
        "asyncpg.ConnectionDoesNotExistError",
        "asyncpg.ConnectionFailureError",
        "ConnectionResetError",
        "BrokenPipeError",
    ):
        classe = h.classe_de_excecao(grafia)
        assert classe is not None, grafia
        assert issubclass(classe, retentaveis), grafia


def test_excecoes_do_handler_achata_tupla() -> None:
    arv = _arv("try:\n    pass\nexcept (ValueError, os.error):\n    pass\n")
    handler = next(n for n in ast.walk(arv) if isinstance(n, ast.ExceptHandler))
    assert h.excecoes_do_handler(handler) == ["ValueError", "os.error"]
