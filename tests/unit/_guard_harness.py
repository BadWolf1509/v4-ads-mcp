"""Travessia, escopo e casamento compartilhados pelos guards estruturais.

Existe porque 17 guards reimplementaram cada um a própria varredura, e cada
reimplementação trouxe o próprio defeito de cobertura: substring no texto do
arquivo, leitura linha a linha, `glob` não-recursivo, igualdade de nome de
classe em vez de subclasse, caminho relativo que vê zero arquivos fora da raiz.
Nenhum desses e um erro de raciocínio sobre a invariante — são todos erros de
varredura. Centralizar a varredura é o que impede o 18º.

Regra central: **um scanner que devolve zero arquivos levanta `EscopoVazioError`
em vez de devolver lista vazia.** Guard que varreu nada passa por vacuidade, e
foi exatamente assim que o guard do relógio ficou verde fora da raiz do repo
(medido em 2026-09-06).
"""

from __future__ import annotations

import ast
import builtins
import importlib
from collections.abc import Iterable
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
SRC = RAIZ / "src"
TEMPLATES = SRC / "web" / "templates"
TESTES = RAIZ / "tests"

_IGNORADOS = frozenset(
    {
        "__pycache__",
        ".venv",
        ".git",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "node_modules",
    }
)


class EscopoVazioError(AssertionError):
    """Um guard que varre zero arquivos não é um guard."""


def _coletar(caminhos: Iterable[Path], *, raiz: Path, padrao: str) -> list[Path]:
    """Filtra `_IGNORADOS`, ordena e resolve para absoluto.

    O `.resolve()` mora AQUI — não em cada função pública que monta `raiz` —
    porque `_coletar` é o único ponto por onde toda varredura passa. Uma
    função de escopo nova, que ainda nem existe, herda a garantia de caminho
    absoluto sem copiar nada: basta chamar `_coletar` (achado da rodada 2 de
    revisão — antes, `.resolve()` vivia copiado nas 4 funções que aceitam
    `raiz`, e uma função futura não herdaria a garantia sem lembrar de
    repetir a cópia).
    """
    achados = sorted(p.resolve() for p in caminhos if not (set(p.parts) & _IGNORADOS))
    if not achados:
        raise EscopoVazioError(
            f"escopo vazio: nenhum {padrao} sob {raiz.resolve()}. Um guard que "
            "varre zero arquivos passa por vacuidade — foi assim que o guard "
            "do relógio ficou verde ao rodar de fora da raiz do repo "
            "(2026-09-06). Confira o caminho: ele precisa ser absoluto, "
            "derivado de __file__."
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


def workflows(raiz: Path | None = None) -> list[Path]:
    """Todo .yml sob `raiz` (default: .github/workflows). Não-recursivo —
    workflow do GitHub Actions não vive em subdiretório."""
    raiz = raiz if raiz is not None else (RAIZ / ".github" / "workflows")
    return _coletar(raiz.glob("*.yml"), raiz=raiz, padrao="*.yml")


def arvore(caminho: Path) -> ast.Module:
    """AST de um arquivo, lido sempre em utf-8."""
    return ast.parse(caminho.read_text(encoding="utf-8"))


def rel(caminho: Path) -> str:
    """Caminho relativo à raiz, para mensagem de erro legível."""
    return str(caminho.relative_to(RAIZ)).replace("\\", "/")


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
    return [n for n in ast.walk(arv) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]


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
