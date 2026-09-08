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

# Critério de pertencimento (nenhum destes nomes tinha essa regra escrita —
# foi por isso que `.superpowers` ficou de fora): entra aqui o diretório que é
# TODO ele scratch de ferramenta — gerado por processo (venv, cache de
# lint/tipo/teste, bundler, editor ou agente), não versionado, cujo conteúdo
# não é fonte nem documentação do projeto. Um nome só PARCIALMENTE ignorado
# (ex.: `.claude`, que versiona `settings.json` e `agents/*.md` ao lado de
# `worktrees/` efêmero) NÃO entra: como o filtro casa pelo NOME em qualquer
# posição do caminho (`set(p.parts) & _IGNORADOS`), excluir esse nome
# apagaria também o conteúdo versionado que mora ao lado do estado efêmero.
_IGNORADOS = frozenset(
    {
        "__pycache__",
        ".venv",
        ".git",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "node_modules",
        # Diretório de trabalho dos agentes (briefs, relatórios, notas de
        # revisão) — git-ignored (.gitignore). Sem esta entrada, `markdown()`
        # varria o texto que um REVISOR escreveu descrevendo este mesmo
        # achado (citando o padrão proibido do F113 como exemplo), e o guard
        # ficava vermelho ou verde conforme o que estivesse ali naquele
        # minuto — um gate não-determinístico deixa de ser gate (medido
        # 2026-09-06: `.superpowers/sdd/.../task-4-review.md` acusado).
        ".superpowers",
    }
)


class EscopoVazioError(AssertionError):
    """Um guard que varre zero arquivos não é um guard."""


def _coletar(
    caminhos: Iterable[Path], *, raiz: Path, padrao: str, vazio_ok: bool = False
) -> list[Path]:
    """Filtra `_IGNORADOS`, ordena e resolve para absoluto.

    O `.resolve()` mora AQUI — não em cada função pública que monta `raiz` —
    porque `_coletar` é o único ponto por onde toda varredura passa. Uma
    função de escopo nova, que ainda nem existe, herda a garantia de caminho
    absoluto sem copiar nada: basta chamar `_coletar` (achado da rodada 2 de
    revisão — antes, `.resolve()` vivia copiado nas 4 funções que aceitam
    `raiz`, e uma função futura não herdaria a garantia sem lembrar de
    repetir a cópia).

    `vazio_ok=True` desliga o `EscopoVazioError` e **só é legítimo quando o
    vazio não é vacuidade** — isto é, quando o conjunto varrido é uma
    *relação* de um arquivo (os saltos que ELE faz), não o escopo do guard.
    Um módulo que não delega nada tem zero saltos por construção, e nesse
    caso a não-vacuidade tem que ser afirmada em outro lugar (o guard do
    truncamento a afirma com piso de tamanho sobre a lista de tools). NÃO use
    esta flag para calar um scanner de escopo: foi exatamente varrer zero
    arquivos em silêncio que deixou o guard do relógio verde fora da raiz
    (2026-09-06).
    """
    achados = sorted(p.resolve() for p in caminhos if not (set(p.parts) & _IGNORADOS))
    if vazio_ok:
        return achados
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

    NÃO enxerga despacho dinâmico: `getattr(mod, "alvo")()`, subscript
    (`funcs["alvo"]()`, `locals()["alvo"]()`) ou decorator bare sem
    parênteses (`@alvo` sobre uma função — o Python chama `alvo(f)`, mas o
    AST não materializa nenhum `ast.Call` ali). Limitação estrutural de
    qualquer matcher que opera só sobre sintaxe, não bug desta implementação
    — não há como resolver isso estaticamente sem executar o código.
    Confirmado rodando: `chama()` devolve False pra `getattr(mod, "alvo")()`.
    Nenhum guard deve presumir cobertura aqui.
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
    """Todo `def`/`async def` do módulo — aninhado e método inclusive.

    A função é a unidade do F57: o guard antigo perguntava do ARQUIVO, então
    um executor novo num arquivo que já gateia noutra função passava verde.

    **Não devolve `lambda`** — para isso existe `lambdas()`, separada porque o
    `ast.Lambda` não tem `.name` nem `.body` como lista, e quem itera daqui
    espera as duas coisas. A versão anterior desta docstring prometia "toda
    função do módulo", e a promessa custou cobertura: o guard do F58 confiava
    nela, pulava `ast.Lambda` no laço de filhos por ser "escopo próprio", e o
    corpo do lambda acabava não sendo visitado por ninguém — `g = lambda:
    conn.cursor('q')` passava verde (revisão final, 2026-09-06). Guard que
    precisa de TODO escopo executável soma as duas listas; docstring que
    promete mais do que entrega é o mecanismo que produz o buraco.
    """
    return [n for n in ast.walk(arv) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]


def _arquivo_do_modulo(dotted: str, raiz: Path) -> Path | None:
    """`src.a.b` -> `<raiz>/src/a/b.py`, ou None se não for arquivo."""
    candidato = raiz.joinpath(*dotted.split(".")).with_suffix(".py")
    return candidato if candidato.is_file() else None


def _vinculos_de_src(arv: ast.Module, raiz: Path) -> dict[str, tuple[Path, str | None]]:
    """Nome local -> (arquivo `src.*`, símbolo).

    Símbolo `None` marca **vínculo de módulo** (o nome local É o módulo, e a
    função só se sabe qual no call-site: `mod.f()`); símbolo preenchido marca
    **vínculo de função** (`from ... import f`, chamada como `f()`).

    As duas formas existem vivas neste repo e a segunda é a que a rodada 1
    perdeu: `from src.db.repositories import audit_log` +
    `audit_log.list_for_manager(...)` é como `get_my_audit_log` chega no
    repositório — 449 imports `from src.` só em `src/mcp/tools/`.

    A desambiguação `from src.a import b` (b é módulo? ou símbolo de
    `src/a.py`?) é feita na ordem que o Python usa: submódulo primeiro
    (`src/a/b.py`), símbolo do pacote-arquivo depois (`src/a.py`).
    """
    vinculos: dict[str, tuple[Path, str | None]] = {}
    for no in ast.walk(arv):
        if (
            isinstance(no, ast.ImportFrom)
            and no.module
            and (no.module == "src" or no.module.startswith("src."))
        ):
            do_pacote = _arquivo_do_modulo(no.module, raiz)
            for a in no.names:
                submodulo = _arquivo_do_modulo(f"{no.module}.{a.name}", raiz)
                if submodulo is not None:
                    vinculos[a.asname or a.name] = (submodulo, None)
                elif do_pacote is not None:
                    vinculos[a.asname or a.name] = (do_pacote, a.name)
        elif isinstance(no, ast.Import):
            for a in no.names:
                if not (a.name == "src" or a.name.startswith("src.")):
                    continue
                arquivo = _arquivo_do_modulo(a.name, raiz)
                if arquivo is None:
                    continue
                # Sem alias, `import src.a.b` liga o nome `src` e a chamada
                # sai escrita inteira (`src.a.b.f()`) — por isso a chave é o
                # caminho pontilhado, casado adiante por `_caminho_pontilhado`.
                vinculos[a.asname or a.name] = (arquivo, None)
    return vinculos


def funcoes_chamadas_de_src(
    arquivo: Path, *, raiz: Path | None = None
) -> list[tuple[Path, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """As FUNÇÕES `src.*` que `arquivo` de fato chama, um salto — não os
    módulos delas, e não travessia transitiva.

    **A unidade é a função, e isso não é detalhe.** A versão anterior
    (`modulos_importados_de_src`, aposentada aqui) devolvia o MÓDULO, e um
    guard que varre o módulo inteiro absolve a tool por qualquer menção em
    qualquer canto do helper — mesmo em função que a tool nunca chama. Medido
    em 2026-09-07: `src/google_ads/reports.py` está a um salto de 20 das 26
    tools com `limit`, então uma única chave nova em qualquer função dele
    absolveria 8 das 9 devedoras de uma vez. É a família do F57 — escopo um
    andar acima do que a invariante fala.

    Resolve as duas formas de chamada que existem no repo:

    - `from src.a.b import f` + `f(...)`      -> (`src/a/b.py`, def f)
    - `from src.a import b`   + `b.f(...)`    -> (`src/a/b.py`, def f)
    - `import src.a.b as m`   + `m.f(...)`    -> (`src/a/b.py`, def f)
    - `import src.a.b`        + `src.a.b.f()` -> (`src/a/b.py`, def f)

    Import só, sem chamada, NÃO entra: importar não é delegar.

    `raiz` é onde `src.<resto>` resolve para `<raiz>/src/<resto>.py` — default
    é a raiz real do repo (`RAIZ`). Parametrizável para um teste de mordida
    montar um `src.` falso sob `tempfile`, sem tocar a árvore real nem
    precisar que o módulo fake seja importável de verdade.

    Limites conhecidos — o salto simplesmente não acontece nestes casos:

    - import relativo (`from .b import f`) — checado que não existe em `src/`
      neste repo (grep 2026-09-07); se aparecer, este scanner cresce.
    - despacho dinâmico (`getattr(mod, "f")()`), igual à limitação de `chama`.
    - `f` que é classe, não função: `funcoes()` não a devolve, então o salto
      simplesmente não acontece.
    - travessia transitiva: se a chave mora dois saltos adiante, não é vista.

    **A direção do erro depende do consumidor, e não é uniforme.** Num guard
    que procura o que TEM que existir, salto perdido erra ACUSANDO — seguro.
    Num guard que procura o que NÃO pode existir (uma constante mentirosa, por
    exemplo), o mesmo salto perdido erra ABSOLVENDO calado. Medido em
    2026-09-07 contra `test_declaracao_de_truncamento`: os quatro casos acima
    fazem uma `"truncated": False` literal num helper passar despercebida.
    Exposição real hoje é zero (nenhum dos módulos alcançados pelas 26 tools
    com `limit` cai nestas formas, e não há literal `truncated` em `src/`), mas
    quem consumir isto num guard negativo tem que fechar a folga por outro
    caminho — não herdar uma garantia que este resolvedor não dá.
    """
    raiz = raiz if raiz is not None else RAIZ
    arv = arvore(arquivo)
    vinculos = _vinculos_de_src(arv, raiz)

    simbolos_por_arquivo: dict[str, set[str]] = {}
    for candidato, simbolo in _alvos_chamados(arv, vinculos):
        simbolos_por_arquivo.setdefault(str(candidato.resolve()), set()).add(simbolo)

    achados: list[tuple[Path, ast.FunctionDef | ast.AsyncFunctionDef]] = []
    for helper in _coletar(
        (Path(p) for p in simbolos_por_arquivo),
        raiz=raiz,
        padrao="módulo `src.*` chamado",
        # Zero saltos é resultado legítimo (tool que não delega), não
        # vacuidade — ver a nota de `vazio_ok` em `_coletar`.
        vazio_ok=True,
    ):
        alvos = simbolos_por_arquivo[str(helper)]
        for fn in funcoes(arvore(helper)):
            if fn.name in alvos:
                achados.append((helper, fn))
    return sorted(achados, key=lambda par: (str(par[0]), par[1].name, par[1].lineno))


def _alvos_chamados(
    arv: ast.Module, vinculos: dict[str, tuple[Path, str | None]]
) -> set[tuple[Path, str]]:
    """Percorre os `ast.Call` e casa cada um contra `vinculos`."""
    alvos: set[tuple[Path, str]] = set()
    for no in ast.walk(arv):
        if not isinstance(no, ast.Call):
            continue
        f = no.func
        if isinstance(f, ast.Name):
            vinculo = vinculos.get(f.id)
            if vinculo is not None and vinculo[1] is not None:
                alvos.add((vinculo[0], vinculo[1]))
        elif isinstance(f, ast.Attribute):
            base = _caminho_pontilhado(f.value)
            if base is None:
                continue
            vinculo = vinculos.get(base)
            if vinculo is not None and vinculo[1] is None:
                alvos.add((vinculo[0], f.attr))
    return alvos


def lambdas(arv: ast.Module) -> list[ast.Lambda]:
    """Todo `lambda` do módulo — o escopo executável que `funcoes()` não vê.

    Um lambda é escopo próprio (o corpo dele não roda quando a linha que o
    define roda) e é a forma mais curta de produzir consumo preguiçoso, que
    é justamente o que o F58 existe para impedir.
    """
    return [n for n in ast.walk(arv) if isinstance(n, ast.Lambda)]


def _caminho_pontilhado(no: ast.expr) -> str | None:
    """Desembrulha uma cadeia de `ast.Attribute` até a raiz, montando o
    caminho pontilhado inteiro (`mod.sub.Erro`, `mod.sub.aninhado.Erro`...).

    Devolve `None` quando a cadeia não termina num `ast.Name` (ex.: atributo
    de uma chamada, `foo().Erro`) — caso em que não existe caminho estático
    pra resolver, e o alvo é descartado por quem chama em vez de contribuir
    um nome truncado que poderia, por coincidência, resolver pra outra classe.
    """
    if isinstance(no, ast.Name):
        return no.id
    if isinstance(no, ast.Attribute):
        base = _caminho_pontilhado(no.value)
        return f"{base}.{no.attr}" if base is not None else None
    return None


def excecoes_do_handler(handler: ast.ExceptHandler) -> list[str]:
    """Nomes escritos no `except`, achatando tupla. `except:` puro devolve [].

    Atributo encadeado (`mod.sub.Erro`) é desembrulhado recursivamente até a
    raiz — tratar só um nível truncava pro último segmento (`mod.sub.Erro`
    virava só "Erro"), e `classe_de_excecao` então resolvia esse nome curto
    contra builtins/asyncpg com sucesso e silenciosamente: uma classe real,
    só que ERRADA, nunca o None seguro que a função promete pro desconhecido.
    """
    if handler.type is None:
        return []
    alvos = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    nomes: list[str] = []
    for a in alvos:
        if isinstance(a, ast.Name):
            nomes.append(a.id)
        elif isinstance(a, ast.Attribute):
            caminho = _caminho_pontilhado(a)
            if caminho is not None:
                nomes.append(caminho)
    return nomes


def classe_de_excecao(nome: str) -> type[BaseException] | None:
    """Resolve o nome escrito no `except` para a CLASSE, para o guard poder
    perguntar `issubclass` em vez de comparar string.

    Namespaces cobertos: `builtins` e `asyncpg` — os dois únicos de onde saem
    as exceções retentáveis deste projeto. Nome que não resolve devolve None, e
    **o guard decide**: o padrão seguro é tratar o desconhecido como ofensor,
    nunca como isento.

    O ramo dotted usa a MESMA allowlist do ramo sem ponto
    (`_NAMESPACES_DE_EXCECAO`): só importa o módulo se a raiz do caminho
    pontilhado estiver na lista. Sem essa checagem, o texto de um `except`
    lido de arquivo-fonte arbitrário (Task 3+ varrendo `src/`) decidiria
    sozinho qual módulo este processo importa — com ela, raiz fora da lista
    devolve None sem nunca chamar `importlib.import_module`.
    """
    if "." in nome:
        raiz = nome.split(".", 1)[0]
        if raiz not in _NAMESPACES_DE_EXCECAO:
            return None
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
