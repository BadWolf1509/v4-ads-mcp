"""§3.2 da spec: tool que corta tem que dizer que cortou.

Por que propriedade e nao lista: a versao "lista de tools que precisam de
`truncated`" passa verde para a tool NOVA que ninguem lembrou de listar, que e
exatamente como as 9 desta frente chegaram a producao. O escopo aqui e derivado
do registry — tool nova com `limit` entra sozinha.

**A unidade da COBRANCA e o CAMINHO DE RETORNO, nao o modulo** (rodada de
correcao 1 do PR 4). A versao anterior coletava toda chave de todo dict
alcancavel a partir do modulo da tool: bastava UM `return` declarar para
absolver todos os outros. Foi assim que o `get_performance_breakdown` —
`truncated` nos dois retornos do ramo `hourly`, nenhum no generico — passou
verde no MESMO commit em que a regressao entrou, devolvendo `limit + 1` linhas
ao gestor. O guard estava la e nao viu, porque afirmava o ADJACENTE ("o modulo
menciona `truncated`") em vez da invariante ("todo retorno que carrega lista
cortavel a declara").

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
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from tests.unit import _guard_harness as h

DEVEDORAS_ATE_A_TASK_2: list[str] = []

# Piso de nao-vacuidade da COBRANCA (nao do escopo): quantos retornos de dict
# literal o guard tem que ter mesmo examinado. Observados 23 em 2026-09-08.
# `_PISO_DE_TOOLS_COM_LIMITE` protege o denominador (26 tools); este protege o
# numerador — um `_retornos_do_handler` que parasse de casar devolveria zero
# ofensor sobre zero retornos e ficaria verde para sempre, que e a forma mais
# silenciosa de um guard morrer.
_PISO_DE_RETORNOS_DE_DICT = 15

# O escopo (tools com `limit`) e o piso dele vivem em `_guard_harness`: este
# guard e o irmao da sentinela (`test_builders_pedem_a_linha_sentinela`)
# dependem do MESMO conjunto, e duas copias divergiriam — a divergencia
# absolveria exatamente a tool que estivesse so numa das listas.
_tools_com_limite = h.tools_com_limite


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


def _chaves_dos_saltos(arquivo: Path, *, raiz: Path | None = None) -> set[str]:
    """So as chaves das FUNCOES `src.*` que a tool chama — sem o modulo dela.

    E o que absolve quem delega a montagem do retorno em vez de repetir a
    chave: `get_assets` devolve `{"customer_id": …, "links": …, "summary":
    summary}`, um dict literal SEM `truncated` no topo, e o campo mora dentro
    do `summary` que `asset_inventory.py::build_inventory` montou. Medido: e a
    unica das 26 cujo retorno de dict literal depende deste salto.
    """
    chaves: set[str] = set()
    for _, funcao, no in _escopo_da_tool(arquivo, raiz=raiz):
        if funcao is not None:
            chaves |= _chaves_de_dicts(no)
    return chaves


def _retornos_do_handler(arv: ast.Module, handler: str) -> list[ast.Return] | None:
    """Os `ast.Return` do corpo do handler — sem descer em `def`/`lambda`
    aninhado. `None` quando o nome nao existe no modulo.

    Nome ausente e tratado pelo chamador como OFENSOR, nunca como absolvicao:
    um scanner que nao acha o alvo tem que falhar fechado, senao renomear o
    handler desliga o guard em silencio.

    Nao descer em funcao aninhada e deliberado — os `return` de um helper
    interno nao sao resposta de tool. `get_ad_schedule` define um `_consulta`
    cujo `return await run_report(...)` nao promete `truncated` a ninguem, e um
    `_fmt` aninhado que devolvesse a linha crua seria acusado por um dict que
    nunca chega ao gestor como resposta.
    """
    alvos = [
        n
        for n in ast.walk(arv)
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name == handler
    ]
    if not alvos:
        return None
    achados: list[ast.Return] = []

    def visita(no: ast.AST) -> None:
        for filho in ast.iter_child_nodes(no):
            if isinstance(filho, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
                continue
            if isinstance(filho, ast.Return):
                achados.append(filho)
            visita(filho)

    visita(alvos[-1])
    return achados


def _eh_envelope_de_erro(d: ast.Dict) -> bool:
    """`{"status": "error", …}` — a forma literal E a que `error_envelope`
    monta (`_mutate_common.py`, mesmo dict com as mesmas chaves).

    Envelope de erro nao carrega lista: nao ha corte que declarar, e cobrar
    `truncated` dele seria ruido que empurraria o proximo autor a decorar o
    erro com um campo falso. O casamento e pelo VALOR constante `"error"`, nao
    pela presenca da chave `status` — `{"status": "ok", "rows": …}` continua
    sendo resposta de dados e continua sendo cobrado.
    """
    return any(
        isinstance(k, ast.Constant)
        and k.value == "status"
        and isinstance(v, ast.Constant)
        and v.value == "error"
        for k, v in zip(d.keys, d.values, strict=True)
    )


def _onde(arquivo: Path) -> str:
    """`h.rel` quando o arquivo mora no repo; o nome nu quando nao mora.

    As mordidas montam um `src.` falso sob `tempfile`, e `Path.relative_to`
    levanta `ValueError` fora da raiz — sem esta ponte, o guard so seria
    executavel contra a arvore real e as mordidas nao poderiam exercita-lo.
    """
    try:
        return h.rel(arquivo)
    except ValueError:
        return arquivo.name


def _retornos_mudos(
    arquivo: Path, handler: str, *, raiz: Path | None = None
) -> tuple[list[str], int]:
    """`(ofensores, quantos retornos de dict foram examinados)`.

    Ofensor = caminho de retorno do handler que entrega um dict literal sem
    `truncated`/`*_truncated` — nem no proprio dict (aninhados inclusive) nem
    numa funcao `src.*` que a tool chame.

    **A folga que fica, dita de proposito:** `return response` (nome de
    variavel) e `return await helper(...)` nao sao dict literal, entao caem no
    criterio antigo — "a chave existe em algum dict do modulo ou de uma funcao
    saltada". Sao 2 tools que montam o retorno em variavel
    (`run_gaql`, `get_ad_schedule`) e 6 que delegam por chamada (as 4 Meta,
    `get_assets` no segundo retorno dela, e `get_change_history`, que desde a
    onda A4 e um wrapper de 3 linhas sobre `consultar_change_history` — o corpo
    saiu do handler para receber o `hoje` da conta injetado). Fechar essa
    metade exigiria seguir a variavel ate a atribuicao (dataflow); a versao
    ingenua — varrer o modulo — e exatamente a que deixou o
    `get_performance_breakdown` passar com a regressao dentro, entao afrouxar
    aqui seria desandar o aperto. Enquanto nao houver dataflow, quem cobre
    esses caminhos e o par por-tool de `test_tools_declaram_truncamento`, que
    chama o handler de verdade e le o valor.
    """
    arv = h.arvore(arquivo)
    retornos = _retornos_do_handler(arv, handler)
    if retornos is None:
        return ([f"{_onde(arquivo)}: handler `{handler}` nao existe no modulo"], 0)
    do_modulo = _chaves_de_dicts(arv)
    dos_saltos = _chaves_dos_saltos(arquivo, raiz=raiz)
    ofensores: list[str] = []
    dicts = 0
    for r in retornos:
        if r.value is None:
            continue
        if isinstance(r.value, ast.Dict):
            if _eh_envelope_de_erro(r.value):
                continue
            dicts += 1
            if not _declara_truncamento(_chaves_de_dicts(r)):
                ofensores.append(f"{_onde(arquivo)}::{handler}:{r.lineno} (dict literal)")
        elif not _declara_truncamento(do_modulo | dos_saltos):
            ofensores.append(f"{_onde(arquivo)}::{handler}:{r.lineno}")
    return ofensores, dicts


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
    """Ratchet de baseline, nao `xfail`. Baseline ZERADA na Task 2.

    A propriedade e, POR CAMINHO DE RETORNO do handler: todo `return` de dict
    literal carrega `truncated` OU `*_truncated` — no proprio dict (aninhados
    inclusive) ou no corpo de uma funcao `src.*` que a tool CHAME (um salto).
    Envelope de erro (`{"status": "error", …}`) e isento: nao carrega lista.
    Retorno que nao e dict literal (`return response`, `return await
    helper(...)`) cai no criterio antigo — a folga esta escrita em
    `_retornos_mudos`, com o motivo. As 9 devedoras de 2026-09-07 fecharam na
    Task 2 deste PR, e a lista encolheu no mesmo commit — que era a metade que
    o `xfail` nao cobrava.

    A lista fica: `== []` puro perderia a mensagem que ensina as duas leituras
    do vermelho, e um debito futuro (tool nova que chegue cortando calada e
    nao possa ser fechada no mesmo PR) volta a ter onde ser anotado sem
    reintroduzir `xfail`. Com ela vazia, o ratchet e simplesmente "nenhuma
    tool com `limit` corta sem dizer".

    Vale so metade da invariante: este guard le o RETORNO, nao a QUERY. Quem
    cobra o `LIMIT {limit + 1}` — sem o qual `truncated` responde `false` para
    sempre — e `test_builders_pedem_a_linha_sentinela`, o irmao que compartilha
    este mesmo escopo via `h.tools_com_limite()`.
    """
    detalhe: dict[str, list[str]] = {}
    dicts_examinados = 0
    for nome, arq, handler in _tools_com_limite():
        mudos, quantos = _retornos_mudos(arq, handler)
        dicts_examinados += quantos
        if mudos:
            detalhe[nome] = mudos
    if dicts_examinados < _PISO_DE_RETORNOS_DE_DICT:
        raise h.EscopoVazioError(
            f"so {dicts_examinados} retornos de dict literal examinados (piso: "
            f"{_PISO_DE_RETORNOS_DE_DICT}, observados 23 em 2026-09-08). O "
            "localizador de handler ou o de `ast.Return` parou de casar, e o "
            "guard estaria absolvendo por nao ter olhado nada."
        )
    sem = sorted(detalhe)
    assert sem == DEVEDORAS_ATE_A_TASK_2, (
        "o conjunto de tools que cortam e nao dizem que cortaram (spec 3.2) "
        f"mudou.\n  medido : {sem}\n  baseline: {DEVEDORAS_ATE_A_TASK_2}\n"
        f"  caminhos: {detalhe}\n"
        "Duas leituras: (a) entrou ofensor novo — um caminho de retorno passou "
        "a entregar lista sem declarar corte, e o lugar de consertar e aquele "
        "`return`, nao esta lista; (b) uma devedora anotada foi fechada — entao "
        "ENCOLHA DEVEDORAS_ATE_A_TASK_2 no mesmo commit."
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
    for nome, arq, _handler in _tools_com_limite():
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


# --------------------------------------------------------------------------
# Mordidas do APERTO desta rodada (por caminho de retorno).
# --------------------------------------------------------------------------


@contextmanager
def _modulo_sintetico(fonte: str) -> Iterator[Path]:
    """Um arquivo `.py` avulso sob tempfile — sem `src.` nenhum, porque estas
    mordidas falam do RETORNO, nao do salto."""
    with tempfile.TemporaryDirectory() as d:
        arquivo = Path(d) / "tool_falsa.py"
        arquivo.write_text(fonte, encoding="utf-8")
        yield arquivo


_DOIS_RETORNOS_UM_MUDO = (
    "def roda(linhas, teto):\n"
    "    if teto:\n"
    '        return {"rows": linhas[:teto], "truncated": len(linhas) > teto}\n'
    '    return {"rows": linhas}\n'
)

_DOIS_RETORNOS_DECLARANDO = (
    "def roda(linhas, teto):\n"
    "    if teto:\n"
    '        return {"rows": linhas[:teto], "truncated": len(linhas) > teto}\n'
    '    return {"rows": linhas, "truncated": len(linhas) > 0}\n'
)


def test_mordida_5_um_retorno_declara_e_o_outro_nao_e_acusado() -> None:
    """A mordida DESTA rodada, e a unica que a implementacao anterior nao passa.

    Handler com DOIS `return` de dict: o primeiro declara `truncated`, o
    segundo nao. O criterio antigo coletava as chaves de TODO dict do modulo,
    via a do primeiro e absolvia — foi exatamente assim que o
    `get_performance_breakdown` (declarando nos dois retornos do ramo `hourly`
    e em nenhum do generico) ficou verde no commit em que a regressao entrou.

    A primeira assercao e o controle positivo do aperto: ela AFIRMA que o
    criterio antigo absolve este modulo. Sem ela, a mordida poderia ficar
    vermelha por outro motivo qualquer e nao provaria que o guard ficou mais
    forte. A segunda metade (os dois declarando => zero ofensor) impede o
    guard trivial que acusasse todo mundo.
    """
    with _modulo_sintetico(_DOIS_RETORNOS_UM_MUDO) as arquivo:
        assert _declara_truncamento(_chaves_alcancaveis(arquivo)), (
            "controle: o criterio ANTIGO (chave em qualquer dict do modulo) "
            "ABSOLVE este modulo — e por isso que a acusacao abaixo prova o aperto"
        )
        ofensores, dicts = _retornos_mudos(arquivo, "roda")
        assert dicts == 2, "controle: os dois retornos de dict tem que ser examinados"
        assert ofensores == ["tool_falsa.py::roda:4 (dict literal)"], ofensores

    with _modulo_sintetico(_DOIS_RETORNOS_DECLARANDO) as arquivo:
        assert _retornos_mudos(arquivo, "roda") == ([], 2)


def test_mordida_6_envelope_de_erro_e_isento_mas_status_ok_nao_e() -> None:
    """A isencao casa o VALOR `"error"`, nao a chave `status`.

    Falha contra: **isencao larga** que absolvesse todo dict com `status`
    (`{"status": "ok", "rows": …}` e resposta de dados e tem que ser cobrada)
    e contra **isencao nenhuma**, que cobraria `truncated` de um envelope de
    erro — que nao carrega lista — e empurraria o proximo autor a decorar o
    erro com um campo falso.
    """
    erro = (
        "def roda(x):\n"
        "    if not x:\n"
        '        return {"status": "error", "error_message": "vazio"}\n'
        '    return {"rows": x, "truncated": len(x) > 1}\n'
    )
    with _modulo_sintetico(erro) as arquivo:
        ofensores, dicts = _retornos_mudos(arquivo, "roda")
        assert ofensores == []
        assert dicts == 1, "o envelope de erro nao entra na contagem de cobrados"

    ok = 'def roda(x):\n    return {"status": "ok", "rows": x}\n'
    with _modulo_sintetico(ok) as arquivo:
        assert _retornos_mudos(arquivo, "roda")[0] == ["tool_falsa.py::roda:2 (dict literal)"]


def test_mordida_7_handler_que_nao_existe_e_ofensor_nao_absolvido() -> None:
    """Falhar FECHADO: renomear o handler nao pode desligar o guard calado.

    Falha contra: **implementacao que devolvesse lista vazia** quando o nome
    nao casa — o conjunto inteiro passaria a ser absolvido por vacuidade, e o
    sintoma seria um guard verde, nao um erro.
    """
    with _modulo_sintetico('def roda(x):\n    return {"rows": x}\n') as arquivo:
        ofensores, dicts = _retornos_mudos(arquivo, "nome_que_nao_existe")
        assert dicts == 0
        assert len(ofensores) == 1 and "nao existe no modulo" in ofensores[0]


def test_mordida_8_retorno_de_funcao_aninhada_nao_e_cobrado() -> None:
    """`def` interno tem escopo proprio: o `return` dele nao e resposta de tool.

    Falha contra: **varredura por `ast.walk`** do corpo do handler, que
    desceria no helper aninhado e cobraria `truncated` de um dict que nunca
    chega ao gestor como resposta. Vivo hoje em `get_ad_schedule`, que define
    um `_consulta` dentro do proprio handler.
    """
    fonte = (
        "def roda(x):\n"
        "    def _linha(r):\n"
        '        return {"id": r}\n'
        '    return {"rows": [_linha(r) for r in x], "truncated": len(x) > 1}\n'
    )
    with _modulo_sintetico(fonte) as arquivo:
        ofensores, dicts = _retornos_mudos(arquivo, "roda")
        assert dicts == 1, "so o retorno do handler conta"
        assert ofensores == []
