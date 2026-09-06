"""Testes do próprio harness.

Um harness de guards com bug é o mesmo defeito um nível acima: todo guard
construído sobre ele passa a mentir junto. Por isso cada scanner é exercitado
contra DOIS fixtures — um que contém a violação e um que não contém.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from types import ModuleType

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


def test_templates_html_desce_em_subdiretorio(tmp_path: Path) -> None:
    """A única propriedade do harness que sobrevivia a ser quebrada.

    Mutação-teste da revisão final: das 13 mutações aplicadas ao harness, 12
    ficaram vermelhas e UMA passou — trocar o `rglob` desta função por `glob`.
    Os dois testes que já existiam não distinguem: o do caminho default ancora
    em `dashboard.html`, que está na RAIZ de `templates/`, e o de
    `node_modules` põe os dois arquivos no topo de `tmp_path`.

    Não é hipótese: **21 dos 31 templates vivem em subdiretório** (`admin/`,
    `legal/`, `sessions/`). Com a mutação aplicada, dos ~11 guards de frontend
    que dependem desta função só um fica vermelho — e mesmo esse só porque
    afirma uma CONTAGEM de consumidores. CSP, handler inline, `style=`, `th
    scope`, nome acessível e `role="button"` seguiriam verdes varrendo 10 de
    31 arquivos, com `admin/` inteiro invisível. É a forma 3 da entrada F155
    (`glob` não-recursivo) reintroduzida um nível acima, dentro do módulo cuja
    razão de existir é fechá-la.

    `fontes_py` e `testes_py` já estão protegidos, mas por acidente de layout:
    os fixtures deles vivem um nível abaixo, então de-recursar qualquer um dos
    dois dispara `EscopoVazioError`. Aqui a recursão é afirmada de propósito.
    """
    (tmp_path / "admin").mkdir()
    (tmp_path / "admin" / "aninhada.html").write_text("x", encoding="utf-8")
    (tmp_path / "raiz.html").write_text("y", encoding="utf-8")

    achados = h.templates_html(tmp_path)

    assert [p.name for p in achados] == ["aninhada.html", "raiz.html"]
    assert (tmp_path / "admin" / "aninhada.html").resolve() in achados


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


def test_markdown_ignora_superpowers(tmp_path: Path) -> None:
    """`.superpowers/` é o scratch dos agentes deste fluxo (briefs, relatórios,
    notas de revisão) — git-ignored (`.gitignore:25`), mas fisicamente
    presente no disco. Sem a exclusão, `markdown()` varria o texto que um
    REVISOR escreveu descrevendo este mesmo achado — citando o padrão
    proibido do F113 como exemplo — e o guard ficava vermelho ou verde
    conforme o que estivesse ali naquele minuto: um gate não-determinístico
    deixa de ser gate (medido 2026-09-06:
    `.superpowers/sdd/2026-09-06-pr0-harness-de-guards/task-4-review.md:36`
    e `:92`, acusados antes desta correção).
    """
    scratch = tmp_path / ".superpowers"
    scratch.mkdir()
    (scratch / "relatorio-de-revisao.md").write_text(
        "nota do revisor citando o padrao do F113", encoding="utf-8"
    )
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


def test_funcoes_nao_devolve_lambda_e_lambdas_devolve() -> None:
    """O par que faltava, e o buraco que a falta produziu.

    `funcoes()` prometia "toda função do módulo" e entregava só `def`/`async
    def`. O guard do F58 confiava na promessa, pulava `ast.Lambda` no laço de
    filhos por ser "escopo próprio", e o corpo do lambda acabava sem dono:
    `g = lambda: conn.cursor('q')` passava verde (revisão final, 2026-09-06).
    O par negativo (`funcoes` NÃO vê) importa tanto quanto o positivo
    (`lambdas` vê): é a metade que documenta por que as duas listas existem.
    """
    arv = _arv("def topo():\n    g = lambda: 1\n    return g\nh = lambda x: x + 1\n")

    assert {f.name for f in h.funcoes(arv)} == {"topo"}
    assert len(h.lambdas(arv)) == 2
    assert all(isinstance(n, ast.Lambda) for n in h.lambdas(arv))


def test_lambdas_vazio_quando_nao_ha_lambda() -> None:
    """Par negativo de `lambdas()`: módulo só com `def` devolve lista vazia.

    Sem ele, um `lambdas()` que devolvesse `ast.walk` inteiro (toda expressão)
    passaria no teste positivo acima — que só conta 2 — mas não aqui.
    """
    assert h.lambdas(_arv("def topo():\n    return 1\n")) == []


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


def test_excecoes_do_handler_desembrulha_atributo_de_dois_e_tres_niveis() -> None:
    """C1: atributo de 2+ niveis nao pode truncar pro ultimo segmento.

    Pre-fix, `except mod.sub.TimeoutError:` virava `["TimeoutError"]` —
    perdendo o prefixo `mod.sub` inteiro. `classe_de_excecao("TimeoutError")`
    entao resolvia contra builtins com SUCESSO, entregando o `TimeoutError`
    embutido do Python: uma resposta afirmativa plausivel e ERRADA sobre um
    `except` que na verdade nomeia outra classe qualquer.
    """
    dois_niveis = _arv("try:\n    pass\nexcept mod.sub.TimeoutError:\n    pass\n")
    tres_niveis = _arv("try:\n    pass\nexcept mod.sub.aninhado.TimeoutError:\n    pass\n")
    handler_2 = next(n for n in ast.walk(dois_niveis) if isinstance(n, ast.ExceptHandler))
    handler_3 = next(n for n in ast.walk(tres_niveis) if isinstance(n, ast.ExceptHandler))

    assert h.excecoes_do_handler(handler_2) == ["mod.sub.TimeoutError"]
    assert h.excecoes_do_handler(handler_3) == ["mod.sub.aninhado.TimeoutError"]


def test_classe_de_excecao_dotted_respeita_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """I2: o ramo dotted não pode importar módulo fora de `_NAMESPACES_DE_EXCECAO`.

    `os.error` é uma classe real (alias de `OSError`, subclasse de
    `BaseException`) — pre-fix isso resolvia com sucesso porque o ramo
    dotted importava QUALQUER módulo escrito no `except`, sem allowlist.
    Prova as duas metades da propriedade: o retorno é None (rejeitado) E o
    import nunca é tentado (espião em `importlib.import_module` registra as
    chamadas reais, em vez de só inferir a partir do retorno).
    """
    chamadas: list[str] = []
    original = importlib.import_module

    def espiao(nome_mod: str) -> ModuleType:
        chamadas.append(nome_mod)
        return original(nome_mod)

    monkeypatch.setattr(h.importlib, "import_module", espiao)

    assert h.classe_de_excecao("os.error") is None
    assert chamadas == []  # raiz "os" fora da allowlist: nunca tentou importar

    assert h.classe_de_excecao("asyncpg.ConnectionDoesNotExistError") is not None
    assert chamadas == ["asyncpg"]  # allowlist nao virou bloqueio geral
