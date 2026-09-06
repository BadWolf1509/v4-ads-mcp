# PR 0 — Harness de guards estruturais

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dar aos 17 guards estruturais uma travessia, um escopo de arquivos e um casamento por AST compartilhados, para que a próxima classe de bug não precise de um scanner novo — e o scanner novo não traga um defeito novo junto.

**Architecture:** Um módulo `tests/unit/_guard_harness.py` passa a ser dono de três coisas que hoje cada guard refaz: (1) escopo de arquivos, sempre recursivo e sempre absoluto, que **levanta erro se varrer zero arquivos**; (2) casamento por AST que resolve `Name`, `Attribute` e alias de import; (3) formato único de relatório. Os 17 guards são convertidos **preservando semântica** — exceto dois, cujo aperto entra aqui porque foi provado que não há violação viva.

**Tech Stack:** Python 3.13, `ast` da stdlib, pytest. Sem dependência nova.

**Spec:** [`docs/superpowers/specs/2026-09-06-correcoes-varredura-design.md`](../specs/2026-09-06-correcoes-varredura-design.md) — seções 3.1 e 3.1.1.

## Global Constraints

- **Nada de produção muda neste PR.** Só arquivos sob `tests/`. Um diff que toque `src/` é sinal de que a conversão saiu do escopo.
- **A suíte tem que continuar verde a cada commit.** Baseline medida em 2026-09-05: `python scripts/check_pre_push.py` → 6/6, 166,7s.
- **Nenhum guard fica mais estrito neste PR**, com exatamente duas exceções (Task 8), e cada uma só depois de provado que não há violação viva.
- **Todo scanner do harness tem dois fixtures sintéticos:** um que contém a violação e um que não contém. O teste afirma que o scanner enxerga o primeiro e não acusa o segundo. Sem isso o harness é só um lugar novo para o mesmo erro morar.
- **PT-BR em docstring e mensagem de erro** — segue o padrão dos guards existentes.
- `mypy --strict` e `ruff` limpos: o gate roda os dois.

---

## Estrutura de arquivos

| arquivo | responsabilidade |
|---|---|
| `tests/unit/_guard_harness.py` (criar) | escopo de arquivos, matchers AST, relatório |
| `tests/unit/test_guard_harness.py` (criar) | testes do harness contra fixtures sintéticos |
| `tests/unit/fixtures_guards/` (criar) | árvore sintética: `com_violacao/`, `sem_violacao/` |
| `tests/unit/test_structural_guards.py` | converter 6 guards |
| `tests/unit/test_ci_local_parity.py` | converter 2 |
| `tests/unit/test_tools_schemas.py` | converter 2 |
| `tests/unit/test_change_freshness.py` | converter 1 |
| `tests/unit/test_no_server_clock_in_google_tools.py` | converter 1 (inclui o caminho relativo) |
| `tests/unit/test_blast_radius_bate_com_as_tools.py` | converter 2 |
| `tests/unit/test_frontend_a11y_guards.py` | converter 3 |
| `tests/unit/test_frontend_responsive_guards.py` | converter 1 |

---

### Task 1: Escopo de arquivos, com a invariante de escopo vazio

**Files:**
- Create: `tests/unit/_guard_harness.py`
- Create: `tests/unit/test_guard_harness.py`
- Create: `tests/unit/fixtures_guards/sem_violacao/modulo.py`
- Create: `tests/unit/fixtures_guards/com_violacao/modulo.py`

**Interfaces:**
- Produces: `RAIZ`, `SRC`, `TEMPLATES: Path`; `EscopoVazioError(AssertionError)`; `fontes_py(raiz: Path | None = None) -> list[Path]`; `templates_html(raiz: Path | None = None) -> list[Path]`; `markdown(raiz: Path | None = None) -> list[Path]`; `workflows() -> list[Path]`; `testes_py(raiz: Path | None = None) -> list[Path]`. Todos devolvem caminhos **absolutos**, ordenados, sem `__pycache__`.

**Porque a invariante de escopo vazio é o centro desta task:** medi em 2026-09-06 que `test_no_server_clock_in_google_tools.py:27` usa `TOOLS = Path("src/mcp/tools")` — **relativo**. Rodando de `D:\v4-ads-mcp` o glob vê 74 arquivos; rodando de `src/` ou de `tests/unit/` vê **0**, e o guard passa verde sem ter olhado nada. Um scanner que devolve lista vazia não é um guard, é decoração. Levantar erro nesse caso mata a classe inteira de vacuidade — inclusive as futuras.

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/unit/test_guard_harness.py
"""Testes do próprio harness.

Um harness de guards com bug é o mesmo defeito um nível acima: todo guard
construído sobre ele passa a mentir junto. Por isso cada scanner é exercitado
contra DOIS fixtures — um que contém a violação e um que não contém.
"""

from __future__ import annotations

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
```

E os fixtures:

```python
# tests/unit/fixtures_guards/sem_violacao/modulo.py
"""Árvore sintética SEM a violação. Nenhum guard pode acusar este arquivo."""

from src.db.connection import _DROPPED_CONNECTION_ERRORS


def leitura_protegida() -> None:
    try:
        pass
    except _DROPPED_CONNECTION_ERRORS:
        pass
```

```python
# tests/unit/fixtures_guards/com_violacao/modulo.py
"""Árvore sintética COM a violação, uma de cada classe que o harness precisa
enxergar. Serve de alvo positivo para os testes do harness — nenhum guard de
produção varre este diretório."""

import asyncpg
from asyncpg import PostgresConnectionError as PCE


def repete_a_tupla_literal() -> None:
    try:
        pass
    except asyncpg.ConnectionDoesNotExistError:  # subclasse: o guard tem que ver
        pass


def usa_alias_de_import() -> None:
    try:
        pass
    except PCE:  # alias: o guard tem que ver
        pass


def chama_por_alias() -> None:
    from src.google_ads.client import build_client_for_manager as construir

    construir()
```

- [ ] **Step 2: Rodar para verificar que falha**

Run: `python -m pytest tests/unit/test_guard_harness.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'tests.unit._guard_harness'`

- [ ] **Step 3: Implementar o harness — parte do escopo**

```python
# tests/unit/_guard_harness.py
"""Travessia, escopo e casamento compartilhados pelos guards estruturais.

Existe porque 17 guards reimplementaram cada um a própria varredura, e cada
reimplementação trouxe o próprio defeito de cobertura: substring no texto do
arquivo, leitura linha a linha, `glob` não-recursivo, igualdade de nome de
classe em vez de subclasse, caminho relativo que vê zero arquivos fora da raiz.
Nenhum desses é um erro de raciocínio sobre a invariante — são todos erros de
varredura. Centralizar a varredura é o que impede o 18º.

Regra central: **um scanner que devolve zero arquivos levanta `EscopoVazioError`
em vez de devolver lista vazia.** Guard que varreu nada passa por vacuidade, e
foi exatamente assim que o guard do relógio ficou verde fora da raiz do repo
(medido em 2026-09-06).
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
SRC = RAIZ / "src"
TEMPLATES = SRC / "web" / "templates"
TESTES = RAIZ / "tests"

_IGNORADOS = frozenset({"__pycache__", ".venv", ".git", ".mypy_cache", ".ruff_cache", "node_modules"})


class EscopoVazioError(AssertionError):
    """Um guard que varre zero arquivos não é um guard."""


def _coletar(caminhos: Iterable[Path], *, raiz: Path, padrao: str) -> list[Path]:
    achados = sorted(p for p in caminhos if not (set(p.parts) & _IGNORADOS))
    if not achados:
        raise EscopoVazioError(
            f"escopo vazio: nenhum {padrao} sob {raiz}. Um guard que varre zero "
            "arquivos passa por vacuidade — foi assim que o guard do relógio "
            "ficou verde ao rodar de fora da raiz do repo (2026-09-06). "
            "Confira o caminho: ele precisa ser absoluto, derivado de __file__."
        )
    return achados


def fontes_py(raiz: Path | None = None) -> list[Path]:
    """Todo .py sob `raiz` (default: src/). Recursivo, absoluto, ordenado."""
    raiz = raiz if raiz is not None else SRC
    return _coletar(raiz.rglob("*.py"), raiz=raiz, padrao="*.py")


def testes_py(raiz: Path | None = None) -> list[Path]:
    """Todo .py sob tests/. Recursivo — subpacote novo não escapa."""
    raiz = raiz if raiz is not None else TESTES
    return _coletar(raiz.rglob("*.py"), raiz=raiz, padrao="*.py")


def templates_html(raiz: Path | None = None) -> list[Path]:
    raiz = raiz if raiz is not None else TEMPLATES
    return _coletar(raiz.rglob("*.html"), raiz=raiz, padrao="*.html")


def markdown(raiz: Path | None = None) -> list[Path]:
    """Todo .md do repositório, RECURSIVO — inclui docs/, que o guard do F113
    não enxergava (`_RAIZ.glob("*.md")` só pega a raiz)."""
    raiz = raiz if raiz is not None else RAIZ
    return _coletar(raiz.rglob("*.md"), raiz=raiz, padrao="*.md")


def workflows() -> list[Path]:
    d = RAIZ / ".github" / "workflows"
    return _coletar(d.glob("*.yml"), raiz=d, padrao="*.yml")


def arvore(caminho: Path) -> ast.Module:
    """AST de um arquivo, lido sempre em utf-8."""
    return ast.parse(caminho.read_text(encoding="utf-8"))


def rel(caminho: Path) -> str:
    """Caminho relativo à raiz, para mensagem de erro legível."""
    return str(caminho.relative_to(RAIZ)).replace("\\", "/")
```

- [ ] **Step 4: Isentar os fixtures do lint — eles contêm violação DE PROPÓSITO**

O gate roda `ruff check src tests` e `ruff format --check src tests` (medido em
`scripts/_runner.py:24-25`), então os fixtures **são lintados**. Eles existem
para conter código que o linter reprova (import não usado, `except` com `pass`),
e sem isenção o gate fica vermelho no primeiro commit.

Acrescentar a `pyproject.toml`, logo abaixo da isenção que já existe para
`test_rate_limit.py` (mesmo precedente, mesmo motivo):

```toml
[tool.ruff.lint.per-file-ignores]
"tests/unit/test_rate_limit.py" = ["F401"]  # spec-provided file; unused imports intentional
"tests/unit/fixtures_guards/**" = ["F401", "B", "SIM"]  # árvore sintética: a violação É o conteúdo
```

E rodar o formatador nos fixtures, porque `--check` não perdoa:

```bash
python -m ruff format tests/unit/fixtures_guards/
```

- [ ] **Step 5: Rodar para verificar que passa**

Run: `python -m pytest tests/unit/test_guard_harness.py -q`
Expected: PASS (3 testes)

Run: `python -m ruff check src tests && python -m ruff format --check src tests`
Expected: sem ofensa. Se `F401` aparecer nos fixtures, a isenção do Step 4 não
pegou — confira o glob (`**`, não `*`).

- [ ] **Step 6: Commit**

```bash
git add tests/unit/_guard_harness.py tests/unit/test_guard_harness.py tests/unit/fixtures_guards/ pyproject.toml
git commit -m "test(guards): harness com escopo de arquivos que recusa varrer nada"
```

---

### Task 2: Matchers por AST — chamada, função e exceção

**Files:**
- Modify: `tests/unit/_guard_harness.py`
- Modify: `tests/unit/test_guard_harness.py`

**Interfaces:**
- Consumes: `arvore()`, `fontes_py()` da Task 1.
- Produces:
  - `nomes_locais(arv: ast.Module, alvo: str) -> set[str]` — o nome mais todos os alias de import que apontam para ele.
  - `chama(no: ast.AST, alvo: str, *, arv: ast.Module) -> bool`
  - `funcoes(arv: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]` — inclui aninhadas e métodos.
  - `excecoes_do_handler(h: ast.ExceptHandler) -> list[str]` — nomes achatados da tupla.
  - `classe_de_excecao(nome: str) -> type[BaseException] | None`

**Por que `classe_de_excecao` resolve de verdade em vez de comparar string:** o guard do F91 compara `{e.__name__ for e in _DROPPED_CONNECTION_ERRORS}` com o nome escrito no `except`. Probei em 2026-09-06 que 4 das 5 grafias ofensoras passam — `asyncpg.ConnectionDoesNotExistError`, `ConnectionResetError`, `(asyncpg.ConnectionFailureError, BrokenPipeError)` e alias — e as quatro são `issubclass` de verdade dos membros da constante. A propriedade só se afirma resolvendo a classe.

- [ ] **Step 1: Escrever o teste que falha**

```python
# acrescentar a tests/unit/test_guard_harness.py
import ast


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
```

- [ ] **Step 2: Rodar para verificar que falha**

Run: `python -m pytest tests/unit/test_guard_harness.py -q -k "chama or funcoes or excecao or subclasse"`
Expected: FAIL com `AttributeError: module '_guard_harness' has no attribute 'chama'`

- [ ] **Step 3: Implementar os matchers**

```python
# acrescentar a tests/unit/_guard_harness.py
import builtins
import importlib

_NAMESPACES_DE_EXCECAO = ("builtins", "asyncpg")


def nomes_locais(arv: ast.Module, alvo: str) -> set[str]:
    """`alvo` mais todo alias de import que aponte para ele.

    `from x import alvo as outro` fazia o guard antigo perder o call-site
    inteiro — o nome escrito na chamada não é o nome do símbolo.
    """
    nomes = {alvo}
    for no in ast.walk(arv):
        if isinstance(no, ast.ImportFrom):
            for a in no.names:
                if a.name == alvo and a.asname:
                    nomes.add(a.asname)
        elif isinstance(no, ast.Import):
            for a in no.names:
                if a.name.rpartition(".")[2] == alvo and a.asname:
                    nomes.add(a.asname)
    return nomes


def chama(no: ast.AST, alvo: str, *, arv: ast.Module) -> bool:
    """True se a subárvore `no` contém chamada a `alvo`.

    Resolve `Name` (`alvo()`), `Attribute` (`mod.alvo()`) e alias.
    """
    nomes = nomes_locais(arv, alvo)
    for sub in ast.walk(no):
        if not isinstance(sub, ast.Call):
            continue
        f = sub.func
        if isinstance(f, ast.Name) and f.id in nomes:
            return True
        if isinstance(f, ast.Attribute) and f.attr in nomes:
            return True
    return False


def funcoes(arv: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Toda função do módulo — aninhada e método inclusive.

    A função é a unidade do F57: o guard antigo perguntava do ARQUIVO, então
    um executor novo num arquivo que já gateia noutra função passava verde.
    """
    return [
        n for n in ast.walk(arv) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    ]


def excecoes_do_handler(handler: ast.ExceptHandler) -> list[str]:
    """Nomes escritos no `except`, achatando tupla. `except:` puro devolve []."""
    if handler.type is None:
        return []
    alvos = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    nomes: list[str] = []
    for a in alvos:
        if isinstance(a, ast.Name):
            nomes.append(a.id)
        elif isinstance(a, ast.Attribute) and isinstance(a.value, ast.Name):
            nomes.append(f"{a.value.id}.{a.attr}")
        elif isinstance(a, ast.Attribute):
            nomes.append(a.attr)
    return nomes


def classe_de_excecao(nome: str) -> type[BaseException] | None:
    """Resolve o nome escrito no `except` para a CLASSE, para o guard poder
    perguntar `issubclass` em vez de comparar string.

    Namespaces cobertos: `builtins` e `asyncpg` — os dois únicos de onde saem
    as exceções retentáveis deste projeto. Nome que não resolve devolve None, e
    **o guard decide**: o padrão seguro é tratar o desconhecido como ofensor,
    nunca como isento.
    """
    if "." in nome:
        mod, _, attr = nome.rpartition(".")
        try:
            obj = getattr(importlib.import_module(mod), attr)
        except (ImportError, AttributeError):
            return None
    else:
        obj = getattr(builtins, nome, None)
        if obj is None:
            for ns in _NAMESPACES_DE_EXCECAO:
                try:
                    obj = getattr(importlib.import_module(ns), nome, None)
                except ImportError:
                    obj = None
                if obj is not None:
                    break
    return obj if isinstance(obj, type) and issubclass(obj, BaseException) else None
```

- [ ] **Step 4: Rodar para verificar que passa**

Run: `python -m pytest tests/unit/test_guard_harness.py -q`
Expected: PASS (8 testes)

- [ ] **Step 5: Commit**

```bash
git add tests/unit/_guard_harness.py tests/unit/test_guard_harness.py
git commit -m "test(guards): matchers AST com alias, funcao e resolucao de excecao"
```

---

### Task 3: Converter os 6 guards de `test_structural_guards.py`

**Files:**
- Modify: `tests/unit/test_structural_guards.py`

**Interfaces:**
- Consumes: `fontes_py()`, `testes_py()`, `arvore()`, `rel()` do harness.

**Semântica preservada.** Esta task **não aperta nada** — troca `_py_files()` por `h.fontes_py()`, `_calls()` por `h.chama()`, e o glob não-recursivo da linha 254 por `h.testes_py()`. Os guards continuam acusando exatamente o que acusavam. O aperto do F57 vai para o PR 3; o do F91 e o do F58, para a Task 8 deste plano.

- [ ] **Step 1: Registrar o baseline antes de tocar**

Run: `python -m pytest tests/unit/test_structural_guards.py -q`
Expected: PASS. Anote o número de testes — ele não pode mudar nesta task.

- [ ] **Step 2: Substituir os helpers locais pelo harness**

Remover `SRC`, `_py_files` e `_calls` do topo do arquivo e importar o harness:

```python
import ast

from tests.unit import _guard_harness as h

SRC = h.SRC  # mantido: 3 guards usam `p.relative_to(SRC)` na mensagem
```

Trocar, em cada guard, `_py_files()` → `h.fontes_py()` e `_calls(no, "nome")` → `h.chama(no, "nome", arv=arv)`, onde `arv` é a árvore do módulo (já disponível: os guards fazem `ast.parse` do arquivo).

Na linha 254 (guard do DSN), trocar `integracao.glob("*.py")` por `h.testes_py(integracao)` — recursivo, e agora um subpacote novo em `tests/integration/` não escapa.

- [ ] **Step 3: Rodar e conferir que o resultado é idêntico**

Run: `python -m pytest tests/unit/test_structural_guards.py -q`
Expected: PASS, com o **mesmo número de testes** do Step 1.

- [ ] **Step 4: Provar que a conversão não afrouxou nada**

Para cada um dos 6 guards, aplique a sabotagem que ele deveria pegar **numa cópia do repositório fora da árvore de trabalho** (`git worktree add` num diretório temporário, ou cópia com `shutil.copytree`), rode o guard e confirme vermelho. Nunca edite `src/` da árvore real, e nunca use `git checkout` para desfazer.

Sabotagens, uma por guard:

| guard | sabotagem que tem que ficar VERMELHA |
|---|---|
| F57 | novo arquivo `src/google_ads/x.py` chamando `build_client_for_manager()` sem `ensure_account_access` |
| F57-Meta | novo arquivo chamando `build_meta_api()` fora de `reports.py` |
| F58 | `conn.cursor(...)` sem `async with conn.transaction()` em arquivo novo |
| F83 | `pool.acquire()` num `finally` de topo, sem `best_effort` |
| DSN | arquivo com DSN hardcoded em `tests/integration/` |
| F91 | `except asyncpg.PostgresConnectionError:` literal em arquivo novo |

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_structural_guards.py
git commit -m "test(guards): structural_guards sobre o harness, semantica preservada"
```

---

### Task 4: Converter `test_ci_local_parity.py`, `test_tools_schemas.py` e `test_change_freshness.py`

**Files:**
- Modify: `tests/unit/test_ci_local_parity.py`
- Modify: `tests/unit/test_tools_schemas.py`
- Modify: `tests/unit/test_change_freshness.py`

**Interfaces:**
- Consumes: `markdown()`, `workflows()`, `testes_py()`, `rel()`.

**Atenção — esta task PODE ficar vermelha, e isso é o resultado esperado.** O guard do F113 (`test_ci_local_parity.py:88`) hoje varre `_RAIZ.glob("*.md")`, não-recursivo. Trocar por `h.markdown()` faz ele enxergar `docs/` — e **existe violação viva lá**: `docs/operacao/session-2026-08-19-infra-ci-handoff.md:28` tem `uv pip compile pyproject.toml -o requirements.txt` sem `--universal`, com `pyproject.toml` na linha, que é exatamente a condição de casamento do guard.

Essa linha é o registro histórico do próprio F113 — é uma citação, não uma instrução viva. **Resolva citando em bloco de código com uma nota**, não apagando o histórico:

```markdown
Regerar o lock: `uv pip compile pyproject.toml -o requirements.txt`
<!-- guard-f113: citação do comando QUEBRADO que o F113 corrigiu; o correto leva --universal -->
```

e faça o guard ignorar linha seguida do marcador `guard-f113:`. Se preferir, reescreva a frase para não conter o comando copiável — as duas resolvem; escolha uma e siga.

- [ ] **Step 1: Converter o escopo dos três arquivos**

- `test_ci_local_parity.py:88` → `for caminho in (*h.markdown(), *h.workflows()):`
- `test_tools_schemas.py:76` e `:422` → `h.testes_py(unit_dir)` filtrando por `p.name.startswith("test_")`, em vez de `unit_dir.glob("test_*_builder.py")`. O guard passa a ver **todo** teste que chama um `build_*`, não só os que alguém lembrou de nomear `_builder`.
- `test_change_freshness.py:235` → ver Task 8; nesta task só troque o escopo se houver, e mantenha a asserção como está.

- [ ] **Step 2: Rodar e ver a violação viva aparecer**

Run: `python -m pytest tests/unit/test_ci_local_parity.py -q`
Expected: **FAIL**, apontando `docs/operacao/session-2026-08-19-infra-ci-handoff.md:28`. Se passar, a conversão do escopo não pegou — confira que `h.markdown()` está sendo usado.

- [ ] **Step 3: Resolver a violação e o marcador de isenção**

Aplicar a nota acima no handoff, e no guard:

```python
    for caminho in (*h.markdown(), *h.workflows()):
        linhas = caminho.read_text(encoding="utf-8").splitlines()
        for numero, linha in enumerate(linhas, 1):
            comando = "uv pip compile" in linha and "pyproject.toml" in linha
            if not comando or "--universal" in linha:
                continue
            # Isenção explícita e por LINHA: o marcador tem que estar na linha
            # seguinte. Citar o comando quebrado é legítimo em registro
            # histórico; instruir com ele não é.
            proxima = linhas[numero] if numero < len(linhas) else ""
            if "guard-f113:" in proxima:
                continue
            ofensores.append(f"{h.rel(caminho)}:{numero}")
```

- [ ] **Step 4: Rodar e confirmar verde**

Run: `python -m pytest tests/unit/test_ci_local_parity.py tests/unit/test_tools_schemas.py tests/unit/test_change_freshness.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_ci_local_parity.py tests/unit/test_tools_schemas.py tests/unit/test_change_freshness.py docs/operacao/session-2026-08-19-infra-ci-handoff.md
git commit -m "test(guards): parity e schemas sobre o harness; F113 passa a ver docs/"
```

---

### Task 5: Converter o guard do relógio, incluindo o caminho relativo

**Files:**
- Modify: `tests/unit/test_no_server_clock_in_google_tools.py`

**Interfaces:**
- Consumes: `fontes_py()`, `rel()`.

**O defeito que esta task fecha:** `TOOLS = Path("src/mcp/tools")` é **relativo**. Medido em 2026-09-06: da raiz do repo o glob vê 74 arquivos; de `src/` ou de `tests/unit/`, vê **0** — e o guard passa verde tendo varrido nada. Hoje o gate roda da raiz, então o defeito é latente; com o harness ele fica impossível, porque `fontes_py` levanta `EscopoVazioError` em escopo vazio.

- [ ] **Step 1: Escrever o teste que prova a vacuidade de hoje**

```python
def test_o_guard_do_relogio_recusa_escopo_vazio() -> None:
    """Antes do harness, `Path("src/mcp/tools")` relativo devolvia 0 arquivos de
    qualquer cwd que não fosse a raiz, e o guard passava sem olhar nada."""
    import pytest

    from tests.unit import _guard_harness as h

    with pytest.raises(h.EscopoVazioError):
        h.fontes_py(h.SRC / "mcp" / "tools" / "nao_existe")
```

- [ ] **Step 2: Rodar para verificar que falha**

Run: `python -m pytest tests/unit/test_no_server_clock_in_google_tools.py -q -k recusa`
Expected: FAIL — o import de `_guard_harness` ainda não existe neste arquivo.

- [ ] **Step 3: Trocar o escopo relativo pelo harness**

```python
from tests.unit import _guard_harness as h

TOOLS = h.SRC / "mcp" / "tools"   # absoluto, derivado de __file__


def _arquivos_google() -> list[Path]:
    return [
        p
        for p in h.fontes_py(TOOLS)
        if not p.name.startswith(("meta_", "_meta_")) and p.name not in FORA_COM_MOTIVO
    ]
```

**Não mexa ainda no matcher de `datetime.now`** — o aperto para pegar `utcnow()`, `time.time()` e alias vai no PR 4, junto com as correções da camada de leitura, porque é lá que uma violação viva apareceria.

- [ ] **Step 4: Rodar para verificar que passa**

Run: `python -m pytest tests/unit/test_no_server_clock_in_google_tools.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_no_server_clock_in_google_tools.py
git commit -m "test(guards): relogio com escopo absoluto — fim da vacuidade por cwd"
```

---

### Task 6: Converter os 4 guards de frontend

**Files:**
- Modify: `tests/unit/test_frontend_a11y_guards.py`
- Modify: `tests/unit/test_frontend_responsive_guards.py`

**Interfaces:**
- Consumes: `templates_html()`, `rel()`.

Semântica preservada: `_TEMPLATES.rglob("*.html")` → `h.templates_html()`. O aperto (varrer o fragmento montado em Python, deixar de ser linha-a-linha, derivar a lista fixa de 5 templates do source) vai para o **PR 5**, com as correções do painel — é lá que a violação viva mora (`admin/access.html:27,29` e `admin/access_meta.html:27,29` têm 2 inputs sem label).

- [ ] **Step 1: Registrar o baseline**

Run: `python -m pytest tests/unit/test_frontend_a11y_guards.py tests/unit/test_frontend_responsive_guards.py -q`
Expected: PASS. Anote a contagem.

- [ ] **Step 2: Trocar o scanner**

Em ambos os arquivos, substituir toda ocorrência de `_TEMPLATES.rglob("*.html")` por `h.templates_html()`, e `(_TEMPLATES / "admin").rglob("*.html")` por `h.templates_html(_TEMPLATES / "admin")`.

- [ ] **Step 3: Rodar e conferir contagem idêntica**

Run: `python -m pytest tests/unit/test_frontend_a11y_guards.py tests/unit/test_frontend_responsive_guards.py -q`
Expected: PASS, mesma contagem do Step 1.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_frontend_a11y_guards.py tests/unit/test_frontend_responsive_guards.py
git commit -m "test(guards): guards de frontend sobre o harness"
```

---

### Task 7: Converter `test_blast_radius_bate_com_as_tools.py`

**Files:**
- Modify: `tests/unit/test_blast_radius_bate_com_as_tools.py`

**Interfaces:**
- Consumes: `fontes_py()`, `chama()`, `arvore()`.

Trocar `_TOOLS.glob("*.py")` por `h.fontes_py(_TOOLS)` e `_chama()` local por `h.chama()`. **O aperto — deixar de casar qualquer atributo `.level` e transformar o piso `>= 15` em derivação exata — vai para o PR 3**, junto com a correção do `apply_recommendation`, porque é a mesma invariante e a mesma revisão.

- [ ] **Step 1: Baseline**

Run: `python -m pytest tests/unit/test_blast_radius_bate_com_as_tools.py -q` → PASS, anote a contagem.

- [ ] **Step 2: Trocar scanner e matcher**

- [ ] **Step 3: Rodar** → PASS, mesma contagem.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_blast_radius_bate_com_as_tools.py
git commit -m "test(guards): blast_radius sobre o harness"
```

---

### Task 8: Apertar os dois guards que não têm violação viva

**Files:**
- Modify: `tests/unit/test_structural_guards.py` (guards F91 e F58)

**Interfaces:**
- Consumes: `excecoes_do_handler()`, `classe_de_excecao()`, `funcoes()`, `arvore()`.

Esta é a única task do PR 0 que **aumenta** a estritura, e ela existe aqui — e não nos PRs seguintes — porque a spec exige provar ausência de violação viva antes de apertar, e para estes dois a prova é barata e o resultado é negativo.

- [ ] **Step 1: Provar que não há violação viva, antes de apertar**

Run:
```bash
python -c "import ast,pathlib,sys; sys.path.insert(0,'tests'); from unit import _guard_harness as h; [print(h.rel(p), n.lineno) for p in h.fontes_py() if p.name!='connection.py' for n in ast.walk(h.arvore(p)) if isinstance(n, ast.ExceptHandler) for nm in h.excecoes_do_handler(n) if (c:=h.classe_de_excecao(nm)) and issubclass(c,(__import__('asyncpg').PostgresConnectionError, ConnectionError))]"
```
Expected: **nenhuma linha**. Se imprimir alguma, ela é violação viva do F91: pare, registre como achado novo e trate como Crítico antes de continuar.

- [ ] **Step 2: Escrever o guard novo do F91, afirmando a propriedade**

```python
def test_retentaveis_de_conexao_tem_uma_fonte_de_verdade_so() -> None:
    """F91 (4ª vez) — quem captura exceção de conexão IMPORTA a constante.

    A versão anterior comparava NOME (`{e.__name__ for e in ...}`) e por isso
    passava verde nas quatro grafias que de fato aparecem — medido em
    2026-09-06: `asyncpg.ConnectionDoesNotExistError`, `ConnectionResetError`,
    `asyncpg.ConnectionFailureError`, `BrokenPipeError` e qualquer alias de
    import. As quatro são `issubclass` do que `run_with_reconnect` retenta, que
    é a única coisa que importa. A propriedade só se afirma resolvendo a classe.
    """
    from src.db import connection

    retentaveis = connection._DROPPED_CONNECTION_ERRORS
    ofensores: list[str] = []

    for path in h.fontes_py():
        if path.name == "connection.py":  # quem DEFINE a constante
            continue
        arv = h.arvore(path)
        for no in ast.walk(arv):
            if not isinstance(no, ast.ExceptHandler):
                continue
            for nome in h.excecoes_do_handler(no):
                if nome.endswith("_DROPPED_CONNECTION_ERRORS"):
                    continue  # importou a constante: é exatamente o que se quer
                classe = h.classe_de_excecao(nome)
                if classe is not None and issubclass(classe, retentaveis):
                    ofensores.append(f"{h.rel(path)}:{no.lineno} ({nome})")

    assert not ofensores, (
        "except capturando exceção que `run_with_reconnect` RETENTA, sem importar "
        f"`_DROPPED_CONNECTION_ERRORS`: {ofensores}. Duas fontes de verdade do "
        "mesmo dado divergem — e a divergência aqui reabre o F91 sem teste vermelho."
    )
```

- [ ] **Step 3: Provar por sabotagem que o guard novo morde**

Numa cópia fora da árvore de trabalho, acrescente a um arquivo qualquer de `src/`:

```python
def sabotagem() -> None:
    try:
        pass
    except asyncpg.ConnectionDoesNotExistError:
        pass
```

Run: `python -m pytest tests/unit/test_structural_guards.py -q -k retentaveis`
Expected: **FAIL**, nomeando o arquivo e a linha. Repita com `except ConnectionResetError:` e com um alias. Os três têm que ficar vermelhos — eram os três que passavam antes.

- [ ] **Step 4: Apertar o guard do F58 pelo mesmo método**

O guard atual (`test_structural_guards.py:88`) faz `".cursor(" in text and "conn.transaction()" not in text` — por arquivo, e casa `conn.transaction()` escrito dentro de comentário. Reescrever por AST e **por função**, usando `h.funcoes()` e `h.chama()`: a função que chama `.cursor(` precisa ter `conn.transaction()` no próprio corpo (ou num `async with` que a envolva). Provar por sabotagem: um segundo generator com `conn.cursor(` sem transação, em arquivo que já tem transação noutra função, tem que ficar vermelho.

- [ ] **Step 5: Rodar o gate inteiro**

Run: `python scripts/check_pre_push.py`
Expected: 6/6 verde. **Leia o exit code do processo, nunca o de um `tail` ou `grep` na frente** — pipe antes do `&&` já deixou passar commit com gate vermelho neste projeto.

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_structural_guards.py
git commit -m "test(guards): F91 afirma subclasse, F58 vira por funcao — com sabotagem provada"
```

---

### Task 9: Fecho — documentação e registro

**Files:**
- Modify: `docs/operacao/findings-catalog.md`
- Modify: `CLAUDE.md` (só se couber no orçamento de 24.000 bytes)

- [ ] **Step 1: Registrar o achado no catálogo**

Abrir um ID novo para a classe (sugestão: **F155 — guards sem primitivo comum**), listando os 17 da seção 3.1.1 da spec, com o que foi corrigido neste PR e **o que ficou deliberadamente para os PRs seguintes** (o aperto do F57 no PR 3, do relógio no PR 4, dos de frontend no PR 5). O catálogo cobra essa segunda metade em toda entrada corrigida.

- [ ] **Step 2: Conferir o orçamento do CLAUDE.md antes de escrever nele**

Run: `python -m pytest tests/unit/test_docs_links.py -q -k orcamento`
Expected: PASS. O teto é 24.000 bytes e a folga medida em 2026-09-05 era de 91 bytes — se a linha nova não couber, ela fica só no catálogo.

- [ ] **Step 3: Rodar o gate e abrir o PR**

Run: `python scripts/check_pre_push.py` → 6/6.

```bash
git push -u origin pr0/harness-de-guards
gh pr create --base main --title "test(guards): harness estrutural — travessia, escopo e casamento num lugar so" --body "..."
```

O merge é do Wellington.

---

## Auto-revisão do plano

**Cobertura da spec (seção 3.1 e 3.1.1):** os 17 guards têm destino — 6 na Task 3, 3 na Task 4, 1 na Task 5, 4 na Task 6, 2 na Task 7, e os apertos de 2 deles na Task 8. Os apertos dos 5 restantes estão explicitamente adiados para os PRs 3, 4 e 5, com o motivo (violação viva mora lá).

**Divergência da spec, deliberada e registrada:** a spec dizia "nenhum guard fica mais estrito no PR 0". A Task 8 aperta dois. O motivo é que a regra existia para não travar as outras frentes com CI vermelho, e para estes dois a ausência de violação viva é provada no Step 1 da própria task — então o risco que a regra evitava não existe aqui. Se o Step 1 imprimir alguma linha, a task para e o aperto volta para o PR correspondente.

**Acréscimo à spec:** a invariante de escopo vazio (`EscopoVazioError`) não estava na spec. Ela nasceu da medição de 2026-09-06 sobre o caminho relativo do guard do relógio, e é o elemento de maior alavanca do PR — mata a vacuidade em todos os scanners de uma vez, inclusive nos que ainda não existem.

**Consistência de tipos:** `fontes_py`, `testes_py`, `templates_html`, `markdown` e `workflows` devolvem `list[Path]` absolutos; `chama` devolve `bool`; `funcoes` devolve `list[FunctionDef | AsyncFunctionDef]`; `excecoes_do_handler` devolve `list[str]`; `classe_de_excecao` devolve `type[BaseException] | None`. Os nomes usados nas Tasks 3-8 batem com os definidos nas Tasks 1-2.
