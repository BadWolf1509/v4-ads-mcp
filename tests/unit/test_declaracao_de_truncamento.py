"""§3.2 da spec: tool que corta tem que dizer que cortou.

Por que propriedade e nao lista: a versao "lista de tools que precisam de
`truncated`" passa verde para a tool NOVA que ninguem lembrou de listar, que e
exatamente como as 9 desta frente chegaram a producao. O escopo aqui e derivado
do registry — tool nova com `limit` entra sozinha.

**A unidade do salto e a FUNCAO, nao o modulo** (rodada de correcao 2). A
versao anterior varria o modulo inteiro do helper, e qualquer mencao a
`truncated` em qualquer canto daquele arquivo absolvia a tool. O raio disso,
medido em 2026-09-07: `src/google_ads/reports.py` esta a um salto de 20 das 26
tools com `limit`, `queries/_common.py` de 18 — uma chave nova em QUALQUER
funcao de um deles absolveria 8 das 9 devedoras de uma vez, inclusive as que
nunca surfacam o campo. Escopo um andar acima do que a invariante fala e a
familia do F57.
"""

from __future__ import annotations

import ast
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from src.mcp.tools._registry import all_tools, import_all_tools
from tests.unit import _guard_harness as h

import_all_tools()

# Debito conhecido em 2026-09-07, fechado pela Task 2 deste mesmo PR. NAO e
# lista de escopo — o escopo sai do registry. E baseline de ratchet: fica
# vermelho nas DUAS direcoes (ofensor novo entra, ofensor antigo sai) em vez
# de esconder as duas como o `xfail` fazia. Medido: com `xfail(strict=True)` o
# pytest reportava `xfailed` (suite VERDE) com 9 ofensores, com 13 (salto
# removido) e com 26 (scanner cego) — regressao de producao, quebra total do
# scanner e progresso parcial eram todos indistinguiveis.
DEVEDORAS_ATE_A_TASK_2 = [
    "get_ad_group_performance",
    "get_ad_performance",
    "get_audience_performance",
    "get_campaign_performance",
    "get_change_history",
    "get_geo_performance",
    "get_keyword_performance",
    "get_my_audit_log",
    "get_search_terms_report",
]

# Piso de tamanho do escopo. Em 2026-09-07 sao 26 tools com `limit` de 68 no
# registry — o numero e OBSERVACAO daquele dia, nao teto: tool nova com
# `limit` so faz subir. O piso existe porque `EscopoVazioError` so dispara com
# ZERO: um refactor que tornasse `import_all_tools()` preguicoso e carregasse
# um punhado de tools deixaria o guard varrer uma fracao da superficie sem uma
# palavra — "varreu pouco" e a mesma doenca de "varreu nada", so mais dificil
# de ver.
_PISO_DO_ESCOPO = 20


def _tools_com_limite() -> list[tuple[str, Path]]:
    achados = []
    for t in all_tools():
        props = (t.input_schema or {}).get("properties", {})
        if "limit" not in props:
            continue
        arquivo = Path(sys.modules[t.handler.__module__].__file__ or "")
        achados.append((t.name, arquivo))
    if len(achados) < _PISO_DO_ESCOPO:
        raise h.EscopoVazioError(
            f"so {len(achados)} tools declaram `limit` (piso: {_PISO_DO_ESCOPO}, "
            f"observados 26 em 2026-09-07). O registry nao carregou por inteiro, "
            "e o guard estaria passando sobre uma fracao da superficie."
        )
    return sorted(achados)


def _chaves_de_dicts(no: ast.AST) -> set[str]:
    """Chaves string de TODO dict literal dentro de `no`.

    Deliberadamente largo DENTRO do no: o retorno de varias tools e montado em
    variavel e so depois devolvido, entao olhar so o `ast.Return` veria dict
    vazio. Largo aqui erra para o lado de ABSOLVER, e quem fecha essa folga
    sao as mordidas do fim do arquivo.

    O que NAO e largo e o `no`: quando ele e uma funcao de helper, esta funcao
    ve so o corpo dela — nao o modulo inteiro.
    """
    chaves: set[str] = set()
    for sub in ast.walk(no):
        if isinstance(sub, ast.Dict):
            for k in sub.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    chaves.add(k.value)
    return chaves


def _chaves_do_modulo(arquivo: Path) -> set[str]:
    """`_chaves_de_dicts` do modulo inteiro — usado so para o proprio modulo
    da tool, onde o escopo E o arquivo."""
    return _chaves_de_dicts(h.arvore(arquivo))


def _escopo_da_tool(
    arquivo: Path, *, raiz: Path | None = None
) -> list[tuple[Path, str | None, ast.AST]]:
    """O codigo que o guard le por uma tool: o modulo dela inteiro, MAIS o
    corpo de cada funcao `src.*` que ela de fato chama (um salto).

    Existe como funcao unica de proposito: os dois testes de producao
    (`declara_truncated` e `truncated_constante`) sao um PAR — se enxergassem
    escopos diferentes, um helper que hardcodasse `"truncated": False`
    satisfaria o primeiro e escaparia do segundo, e o par nao fecharia nada.
    Derivar os dois daqui torna a simetria estrutural em vez de mantida a mao.

    Devolve `(arquivo, nome_da_funcao | None, no)`; `None` no nome marca o
    modulo da propria tool.
    """
    escopo: list[tuple[Path, str | None, ast.AST]] = [(arquivo, None, h.arvore(arquivo))]
    for helper, fn in h.funcoes_chamadas_de_src(arquivo, raiz=raiz):
        escopo.append((helper, fn.name, fn))
    return escopo


def _chaves_alcancaveis(arquivo: Path, *, raiz: Path | None = None) -> set[str]:
    """Chaves do modulo da tool mais as das FUNCOES `src.*` que ela chama.

    Cobre a tool que delega a montagem do retorno pra um helper compartilhado
    — `meta_get_ad_performance` e os dois irmaos chamam
    `_meta_performance.py::run_meta_level_performance`, `get_assets` chama
    `asset_inventory.py::build_inventory`, e a chave `truncated` e computada e
    devolvida de verdade la dentro, so que num modulo que um scanner de
    `handler.__module__` nao ve.

    E EXCLUI o caso que vazava: uma tool que chama `reports.py::run_report`
    nao e absolvida por `reports.py` mencionar `truncated` em outra funcao.
    """
    chaves: set[str] = set()
    for _, _, no in _escopo_da_tool(arquivo, raiz=raiz):
        chaves |= _chaves_de_dicts(no)
    return chaves


def _declara_truncamento(chaves: set[str]) -> bool:
    """`truncated` OU qualquer chave terminada em `_truncated`.

    O sufixo cobre `audit_competitor_keywords`: corta DUAS listas
    (`positive_keywords`, `search_terms`) sob o MESMO `limit` e declara duas
    flags compostas (`positive_keywords_truncated`, `search_terms_truncated`)
    em vez de uma `truncated` unica — exigir uma unica ali seria pior
    contrato (perderia qual das duas foi cortada), nao melhor.
    """
    return "truncated" in chaves or any(c.endswith("_truncated") for c in chaves)


def _literais_de_truncamento(
    arquivo: Path, *, raiz: Path | None = None
) -> list[tuple[Path, str | None, int]]:
    """Onde `truncated`/`*_truncated` recebe valor CONSTANTE, no mesmo escopo
    que `_chaves_alcancaveis` le. Devolve `(arquivo, funcao, linha)`."""
    ofensores: list[tuple[Path, str | None, int]] = []
    for origem, funcao, no in _escopo_da_tool(arquivo, raiz=raiz):
        for sub in ast.walk(no):
            if not isinstance(sub, ast.Dict):
                continue
            for k, v in zip(sub.keys, sub.values, strict=True):
                if (
                    isinstance(k, ast.Constant)
                    and isinstance(k.value, str)
                    and (k.value == "truncated" or k.value.endswith("_truncated"))
                    and isinstance(v, ast.Constant)
                ):
                    ofensores.append((origem, funcao, k.lineno))
    return ofensores


def test_toda_tool_com_limite_declara_truncated() -> None:
    """Ratchet de baseline, nao `xfail`.

    A propriedade e "existe chave `truncated` OU `*_truncated`, no modulo do
    handler OU no corpo de uma funcao `src.*` que ele CHAME (um salto)". As 9
    de `DEVEDORAS_ATE_A_TASK_2` nao declaram truncamento em nenhum desses
    lugares; a Task 2 fecha cada uma e ENCOLHE a lista no mesmo commit.

    Escrever `== DEVEDORAS_ATE_A_TASK_2` em vez de `== []` sob `xfail` e o que
    torna o sinal continuo: fica vermelho quando entra ofensor novo
    (regressao) E quando um antigo sai (a lista precisa acompanhar). O escopo
    varrido continua derivado do registry — a enumeracao aqui e da baseline de
    ofensores, nao do que se varre.
    """
    sem = [
        nome
        for nome, arq in _tools_com_limite()
        if not _declara_truncamento(_chaves_alcancaveis(arq))
    ]
    assert sem == DEVEDORAS_ATE_A_TASK_2, (
        "o conjunto de tools que cortam e nao dizem que cortaram (spec 3.2) "
        f"mudou.\n  medido : {sem}\n  baseline: {DEVEDORAS_ATE_A_TASK_2}\n"
        "Duas leituras: (a) entrou ofensor novo — uma tool passou a cortar sem "
        "declarar, e o lugar de consertar e a tool; (b) a Task 2 fechou uma das "
        "devedoras — entao ENCOLHA DEVEDORAS_ATE_A_TASK_2 no mesmo commit."
    )


def test_nenhuma_tool_devolve_truncated_constante() -> None:
    """`"truncated": False` (ou `"algo_truncated": False`) fixo satisfaz o
    teste de cima e mente igual.

    Esta e a assercao que distingue "o campo existe" de "o campo e computado" —
    sem ela o guard de cima e satisfeito por um literal, que e a familia
    "asserir o adjacente a invariante". Cobre o sufixo tambem: uma
    `"search_terms_truncated": False` fixa mentiria exatamente igual.

    Varre o MESMO escopo que `_chaves_alcancaveis`, por construcao (os dois
    derivam de `_escopo_da_tool`).
    """
    ofensores: list[str] = []
    for nome, arq in _tools_com_limite():
        for origem, funcao, linha in _literais_de_truncamento(arq):
            onde = h.rel(origem) + (f"::{funcao}" if funcao else "")
            ofensores.append(f"{nome} -> {onde}:{linha}")
    assert ofensores == [], (
        f"`truncated`/`*_truncated` como literal nao e deteccao, e decoracao: {ofensores}"
    )


# --------------------------------------------------------------------------
# Mordidas. Cada uma tem que ficar VERMELHA contra uma implementacao errada
# concreta, nomeada na docstring — teste que passa contra o codigo bom e
# contra o quebrado nao e guard.
# --------------------------------------------------------------------------

# As duas formas de chamada que existem vivas em `src/`. A segunda e a que a
# rodada 1 perdeu (F4): `from src.db.repositories import audit_log` +
# `audit_log.list_for_manager(...)` e como `get_my_audit_log` chega no
# repositorio, e `src/db/repositories/audit_log.py` e onde a Task 2 vai mexer.
_FORMAS_DE_CHAMADA = {
    "from_modulo_import_funcao": (
        "from src.pacote.helper import montar\n\n\ndef roda(linhas, teto):\n"
        "    return montar(linhas, teto)\n"
    ),
    "from_pacote_import_modulo": (
        "from src.pacote import helper\n\n\ndef roda(linhas, teto):\n"
        "    return helper.montar(linhas, teto)\n"
    ),
}

_CORPO_DECLARA = '    return {"rows": linhas[:teto], "truncated": len(linhas) > teto}\n'
_CORPO_MUDO = '    return {"rows": linhas[:teto]}\n'
_CORPO_LITERAL = '    return {"rows": linhas[:teto], "truncated": False}\n'


def _helper(montar: str, nunca_chamada: str | None = None) -> str:
    """Fonte de um helper sintetico.

    `montar` e a funcao que a tool CHAMA; `nunca_chamada` mora no mesmo
    arquivo e ninguem chama. A diferenca entre as duas e exatamente o que esta
    rodada redesenhou — por isso as duas nascem do mesmo molde, e o unico
    eixo que varia entre as mordidas e ONDE o corpo fica.
    """
    fonte = "def montar(linhas, teto):\n" + montar
    if nunca_chamada is not None:
        fonte += "\n\ndef nunca_chamada(linhas, teto):\n" + nunca_chamada
    return fonte


@contextmanager
def _tool_sintetica(forma: str, helper_src: str) -> Iterator[tuple[Path, Path, Path]]:
    """`src.` falso sob tempfile: um helper e uma tool que o chama.

    Sintetico de proposito — o caminho de producao (`_meta_performance.py`,
    `asset_inventory.py`) so exercita o lado que ABSOLVE, e so dentro do teste
    que compara contra a baseline. Uma mordida precisa de um par que ela mesma
    controla nos dois lados.
    """
    with tempfile.TemporaryDirectory() as d:
        raiz = Path(d)
        pacote = raiz / "src" / "pacote"
        pacote.mkdir(parents=True)
        helper = pacote / "helper.py"
        helper.write_text(helper_src, encoding="utf-8")
        tool = raiz / "tool_delega.py"
        tool.write_text(_FORMAS_DE_CHAMADA[forma], encoding="utf-8")
        yield raiz, tool, helper


def _resolveu(tool: Path, raiz: Path) -> list[tuple[Path, str]]:
    return [(p.resolve(), fn.name) for p, fn in h.funcoes_chamadas_de_src(tool, raiz=raiz)]


@pytest.mark.parametrize("forma", sorted(_FORMAS_DE_CHAMADA))
def test_mordida_1_o_salto_absolve_quando_a_funcao_chamada_declara(forma: str) -> None:
    """Metade POSITIVA do controle: a tool nao declara nada no proprio modulo,
    a funcao que ela chama declara, e por isso ela e absolvida.

    Falha contra: **implementacao que nunca salta** (`_chaves_alcancaveis`
    reduzida a `_chaves_do_modulo`). Foi essa a implementacao errada que a
    revisao instalou por monkeypatch e que passou pelos quatro testes da
    rodada 1 — deletar o salto era 100% invisivel. A segunda assercao prende o
    MOTIVO da absolvicao: se o modulo da tool ja declarasse, o teste passaria
    sem provar que o salto le o destino.

    Roda nas duas formas de chamada; a `from_pacote_import_modulo` e a que a
    rodada 1 nao resolvia (F4).
    """
    with _tool_sintetica(forma, _helper(_CORPO_DECLARA)) as (raiz, tool, helper):
        assert _resolveu(tool, raiz) == [(helper.resolve(), "montar")]
        assert not _declara_truncamento(_chaves_do_modulo(tool)), (
            "controle: a tool sintetica nao pode declarar nada sozinha, senao a "
            "absolvicao abaixo nao prova o salto"
        )
        assert _declara_truncamento(_chaves_alcancaveis(tool, raiz=raiz))


@pytest.mark.parametrize("forma", sorted(_FORMAS_DE_CHAMADA))
def test_mordida_2_o_salto_nao_absolve_por_ter_existido(forma: str) -> None:
    """Metade NEGATIVA: a funcao chamada existe, e resolvida, e nao declara —
    a tool continua acusada.

    Falha contra: **implementacao que confunde "existe import/salto" com "o
    destino declara"** (absolvicao automatica por delegacao). A primeira
    assercao impede o motivo errado: sem ela, uma resolucao vazia daria o
    mesmo `False` e o teste passaria por nao ter olhado nada.
    """
    with _tool_sintetica(forma, _helper(_CORPO_MUDO)) as (raiz, tool, helper):
        assert _resolveu(tool, raiz) == [(helper.resolve(), "montar")]
        assert not _declara_truncamento(_chaves_alcancaveis(tool, raiz=raiz))


@pytest.mark.parametrize("forma", sorted(_FORMAS_DE_CHAMADA))
def test_mordida_3_o_salto_nao_absolve_por_mencao_em_funcao_nao_chamada(forma: str) -> None:
    """O caso que prova o redesenho desta rodada. O helper DECLARA — mas numa
    funcao (`nunca_chamada`) que o handler nao chama. A tool continua acusada.

    Falha contra: **a implementacao por MODULO que estava aqui ate a rodada
    1**, que fazia `chaves |= _chaves_de_retorno(helper)` para o arquivo
    inteiro e seria absolvida por `nunca_chamada`. Esse e o vazamento medido:
    `reports.py` a um salto de 20 das 26 tools com `limit`; uma chave nova em
    qualquer funcao dele absolveria 8 das 9 devedoras.

    A primeira assercao e o controle: `montar` resolve, `nunca_chamada` NAO —
    se a resolucao trouxesse as duas, o `assert not` abaixo falharia; se nao
    trouxesse nenhuma, passaria pelo motivo errado.
    """
    with _tool_sintetica(forma, _helper(_CORPO_MUDO, _CORPO_DECLARA)) as (raiz, tool, helper):
        assert _resolveu(tool, raiz) == [(helper.resolve(), "montar")]
        assert "truncated" in _chaves_do_modulo(helper), (
            "controle: o helper TEM que mencionar truncated em algum lugar, "
            "senao a acusacao abaixo nao prova nada sobre o escopo"
        )
        assert not _declara_truncamento(_chaves_alcancaveis(tool, raiz=raiz))


@pytest.mark.parametrize("forma", sorted(_FORMAS_DE_CHAMADA))
def test_mordida_4_o_anti_decoracao_segue_o_mesmo_escopo(forma: str) -> None:
    """Mordida do par (F6): o anti-decoracao tem que enxergar exatamente o que
    `_chaves_alcancaveis` enxerga — nem menos, nem mais.

    - literal na funcao CHAMADA  => acusado (senao um helper que hardcodasse
      `"truncated": False` satisfaria o teste de cima e escaparia deste);
    - valor computado             => nao acusado (senao o guard cobraria
      decoracao de quem ja detecta);
    - literal em funcao NAO chamada => nao acusado — o falso positivo latente
      que a versao por modulo criava: um `return {"rows": [], "truncated":
      False}` legitimo, como early-return de resultado vazio num helper
      compartilhado, acusaria TODAS as tools que importam o modulo.
    """
    with _tool_sintetica(forma, _helper(_CORPO_LITERAL)) as (raiz, tool, _):
        assert [linha for _, _, linha in _literais_de_truncamento(tool, raiz=raiz)] == [2]

    with _tool_sintetica(forma, _helper(_CORPO_DECLARA)) as (raiz, tool, _):
        assert _literais_de_truncamento(tool, raiz=raiz) == []

    with _tool_sintetica(forma, _helper(_CORPO_DECLARA, _CORPO_LITERAL)) as (raiz, tool, _):
        assert _literais_de_truncamento(tool, raiz=raiz) == []


def test_o_guard_enxerga_as_duas_formas_erradas() -> None:
    """Mordida do scanner de chaves, isolada do salto: `truncated` computado e
    visto, ausencia de `truncated` nao e."""
    with tempfile.TemporaryDirectory() as d:
        bom = Path(d) / "bom.py"
        bom.write_text('def f():\n    return {"rows": [], "truncated": t}\n', encoding="utf-8")
        assert "truncated" in _chaves_do_modulo(bom)

        mudo = Path(d) / "mudo.py"
        mudo.write_text('def f():\n    return {"rows": []}\n', encoding="utf-8")
        assert "truncated" not in _chaves_do_modulo(mudo)
