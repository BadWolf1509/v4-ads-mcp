"""Nenhum `join` alimenta um `IN (...)` GAQL sem validar cada item.

A rodada anterior (`4980eda`) fechou seis sitios; a varredura que produziu
aquela lista de seis era `grep`, e errou nas DUAS pontas — perdeu os quatro
sitios em que o `join` esta inline dentro da f-string, e listou como um so os
dois de `_resolve_names` que reusam o mesmo nome de variavel. Corrigir
instancia enquanto a classe segue aberta e como o 13o sitio nasce amanha. Este
guard e a classe.

**Escopo derivado, nao lista**: varre `src/google_ads/` e `src/mcp/tools/`
inteiros. Arquivo novo entra sozinho.

**Duas formas**, e a segunda e a que o `grep` nao ve:

  A) `ids = ", ".join(...)` e depois `f"... IN ({ids})"` — nome intermediario;
  B) `f"... IN ({','.join(...)})"` — inline.

Uma implementacao que so olhasse `ast.Assign` fica verde na forma B, e foi
exatamente essa a cegueira que deixou `queries/ad_schedule.py` (3 sitios) e
`queries/assets.py` (1) fora da lista original. `test_mordida_2_*` e
`test_o_scan_ve_as_duas_formas_na_arvore_real` mordem esse caso.

**O `pattern` do schema nao e defesa (F87).** Tres dos sitios corrigidos aqui
tinham um comentario dizendo "ids validados `^[0-9]+$` no schema" logo acima da
interpolacao crua. O helper e publico, e chamado de mais de um lugar, e o
proximo chamador pode nao ter schema nenhum — `build_campaign_asset_query` e
`ad_schedule_query` sao builders puros que qualquer teste ou tool futura pode
chamar direto. A defesa mora onde a query e montada.

**Falha FECHADO.** Interpolacao dentro de `IN (` que o resolvedor nao consegue
amarrar a um `join` (uma chamada a helper, um parametro de funcao) e ACUSADA,
nao isenta. Custou uma decisao de desenho nesta rodada: a primeira versao do
fix de `ad_schedule.py` extraia um `_ids(campaign_ids)` para nao repetir o
idioma tres vezes — e isso teria tirado os tres sitios do campo de visao do
guard. Os tres ficaram inline de proposito. Se um helper desses for mesmo
necessario um dia, a resposta e ensinar o guard, nao afrouxa-lo.

**O que este guard NAO ve**, dito de proposito para ninguem herdar garantia que
ele nao da:

- clausula montada por concatenacao (`"... IN (" + ids + ")"`) ou por
  `%`/`.format()` — nao existe nenhuma no repo hoje (todo GAQL e f-string,
  conferido por `grep -i "IN ("` em 2026-09-08), e cobrir uma forma morta
  seria maquinario sem mordida;
- `gaql_in_list()` (`queries/_gaql.py`), que monta `('a', 'b')` COM os
  parenteses e por isso e escrito `IN {gaql_in_list(...)}`, sem o `(` literal
  que este scanner procura. Ele ja escapa cada item via `gaql_string_literal`,
  entao a ausencia nao abre buraco — mas e ausencia, nao aprovacao;
- `", ".join(ids)` cujos itens ja foram passados por `int()` em outra linha
  (`ids = [str(int(x)) for x in cru]`). Isso e acusado. Falso positivo que
  erra para o lado seguro e forca o idioma unico do repo.
"""

from __future__ import annotations

import ast
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from tests.unit import _guard_harness as h

_ESCOPOS = (h.SRC / "google_ads", h.SRC / "mcp" / "tools")

# Piso de tamanho, medido em 2026-09-08: 22 sitios (todos seguros depois desta
# rodada). E OBSERVACAO, nao teto — builder novo so faz subir. Existe porque
# `EscopoVazioError` so dispara com ZERO, e um casador de f-string que parasse
# de enxergar a clausula devolveria "nenhum ofensor" e ficaria verde para
# sempre: "varreu pouco" e a mesma doenca de "varreu nada", so mais dificil de
# ver.
_PISO_DE_SITIOS = 10

# `IN (` imediatamente antes da chave, dentro da MESMA parte constante do
# f-string. Casa pelo texto do `JoinedStr`, nao por leitura de linha do
# arquivo, porque a clausula quase sempre nasce de um bloco `f\"\"\"…\"\"\"` de
# varias linhas onde `IN (` e a chave nao estao na mesma linha fisica.
_IN_ANTES_DA_CHAVE = re.compile(r"\bIN\s*\(\s*$", re.IGNORECASE)

# Os dois idiomas que ESTE repo aceita para por valor de gestor numa query:
# `int(...)` para id numerico, `gaql_string_literal(...)` para texto livre.
_IDIOMAS_SEGUROS = ("int", "gaql_string_literal")


def _eh_join(no: ast.expr) -> bool:
    """`<qualquer coisa>.join(...)`. Casa pelo ATRIBUTO, nao pelo separador —
    o repo escreve `", ".join`, `','.join` e `",".join`, e um casador preso ao
    literal do separador perderia dois dos tres."""
    return (
        isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute) and no.func.attr == "join"
    )


def _joins_atribuidos(arv: ast.Module) -> dict[str, list[tuple[int, ast.Call]]]:
    """nome local -> [(linha, call de `join`)], TODAS as atribuicoes, em ordem.

    Lista, e nao um valor unico, porque o mesmo nome e reatribuido dentro da
    mesma funcao neste repo: `_resolve_names` (`get_change_history.py`) usa
    `ids_clause` duas vezes, uma para `campaign_ids` e outra para
    `ad_group_ids`, 15 linhas depois. Um dicionario nome->ultima atribuicao
    colapsa os dois sitios em um — e foi exatamente esse colapso que fez a
    varredura de 2026-09-08 listar onze sitios onde ha doze.
    """
    achados: dict[str, list[tuple[int, ast.Call]]] = {}
    for sub in ast.walk(arv):
        alvos: list[ast.expr] = []
        valor: ast.expr | None = None
        if isinstance(sub, ast.Assign):
            alvos, valor = sub.targets, sub.value
        elif isinstance(sub, ast.AnnAssign) and sub.value is not None:
            alvos, valor = [sub.target], sub.value
        if valor is None or not _eh_join(valor):
            continue
        assert isinstance(valor, ast.Call)
        for alvo in alvos:
            if isinstance(alvo, ast.Name):
                achados.setdefault(alvo.id, []).append((alvo.lineno, valor))
    return achados


def _atribuicao_vigente(
    nome: str, linha_de_uso: int, atribuidos: dict[str, list[tuple[int, ast.Call]]]
) -> ast.Call | None:
    """A atribuicao de `join` mais PROXIMA acima do uso, ou None.

    "Mais proxima acima", e nao "a ultima do modulo": com o nome reusado, a
    ultima atribuicao e a que vale para o ULTIMO uso, e adotar ela para todos
    faz uma atribuicao segura absolver um uso cru escrito antes dela. Erro que
    absolve calado — o pior tipo num guard.
    """
    candidatos = [(ln, call) for ln, call in atribuidos.get(nome, []) if ln <= linha_de_uso]
    return max(candidatos, key=lambda par: par[0])[1] if candidatos else None


def _seguro(alvo: ast.AST, arv: ast.Module) -> bool:
    """A expressao passa cada item por `int(...)` ou `gaql_string_literal(...)`.

    Usa `h.chama`, que resolve alias de import — `from … import
    gaql_string_literal as lit` nao escapa.
    """
    return any(h.chama(alvo, idioma, arv=arv) for idioma in _IDIOMAS_SEGUROS)


def _joins_em_clausula_in(arquivo: Path) -> list[tuple[int, str, bool]]:
    """(linha, expressao, seguro) de todo `join` que alimenta um `IN (...)` GAQL.

    Duas formas, e a segunda e a que a varredura original perdeu:
      A) `ids = ", ".join(...)` e depois `f"... IN ({ids})"`
      B) `f"... IN ({','.join(...)})"` — inline, sem nome intermediario.

    Interpolacao que nao resolve para um `join` entra com `seguro=False` e a
    propria expressao no lugar do texto do join — falha fechado.
    """
    arv = h.arvore(arquivo)
    atribuidos = _joins_atribuidos(arv)
    achados: list[tuple[int, str, bool]] = []
    for no in ast.walk(arv):
        if not isinstance(no, ast.JoinedStr):
            continue
        anterior = ""
        for parte in no.values:
            if isinstance(parte, ast.Constant) and isinstance(parte.value, str):
                anterior = parte.value
            elif isinstance(parte, ast.FormattedValue):
                if _IN_ANTES_DA_CHAVE.search(anterior):
                    linha = getattr(parte, "lineno", no.lineno)
                    expr = parte.value
                    alvo: ast.expr | None = expr if _eh_join(expr) else None
                    if alvo is None and isinstance(expr, ast.Name):
                        alvo = _atribuicao_vigente(expr.id, linha, atribuidos)
                    if alvo is None:
                        achados.append((linha, ast.unparse(expr), False))
                    else:
                        achados.append((linha, ast.unparse(alvo), _seguro(alvo, arv)))
                anterior = ""
    return sorted(achados)


def _varre_a_arvore() -> tuple[list[str], int]:
    """`(ofensores, total de sitios examinados)` sobre o escopo de producao."""
    ofensores: list[str] = []
    total = 0
    for escopo in _ESCOPOS:
        for arquivo in h.fontes_py(escopo):
            for linha, expressao, seguro in _joins_em_clausula_in(arquivo):
                total += 1
                if not seguro:
                    ofensores.append(f"{h.rel(arquivo)}:{linha} -> {expressao}")
    return sorted(ofensores), total


def test_nenhum_id_entra_cru_na_clausula_in() -> None:
    """A propriedade: todo `join` que alimenta um `IN (...)` valida cada item.

    Ofensor aqui nao e estilo. `", ".join(ids)` com um id que nao e id monta
    clausula GAQL arbitraria a partir de texto que o gestor escreveu — e em
    `update_ad_group_bid`/`update_keyword_bid` isso acontece no lookup que
    decide o que a mutacao vai escrever.
    """
    ofensores, total = _varre_a_arvore()
    if total < _PISO_DE_SITIOS:
        raise h.EscopoVazioError(
            f"so {total} clausulas `IN (…)` examinadas (piso: {_PISO_DE_SITIOS}, "
            "observadas 22 em 2026-09-08). O casador de f-string parou de "
            "enxergar a clausula, e um guard que nao acha nada para checar "
            "passa por vacuidade."
        )
    assert ofensores == [], (
        "id entrando cru na clausula `IN (…)` do GAQL. O idioma do repo e "
        '`", ".join(str(int(x)) for x in ids)` para id numerico e '
        "`gaql_string_literal` para texto livre — e o `pattern` do schema a "
        "montante NAO conta (F87: o helper e chamado de mais de um lugar):\n  "
        + "\n  ".join(ofensores)
    )


def test_o_scan_ve_as_duas_formas_na_arvore_real() -> None:
    """Controle positivo do casador contra producao, uma assercao por forma.

    Falha contra: **implementacao cega a uma das formas**. O piso de 22 nao
    pega isso sozinho — perder a forma B inteira derruba o total para 18, que
    passa folgado no piso de 10. `queries/ad_schedule.py` so tem sitios da
    forma B (3) e `queries/_common.py` so tem da forma A (8), entao cada
    arquivo isola uma metade do casador.
    """
    forma_b = _joins_em_clausula_in(h.SRC / "google_ads" / "queries" / "ad_schedule.py")
    assert len(forma_b) >= 3, (
        "ad_schedule.py so tem `IN ({','.join(...)})` INLINE: lista vazia aqui "
        f"significa que o guard perdeu a forma B por inteiro. {forma_b}"
    )
    forma_a = _joins_em_clausula_in(h.SRC / "google_ads" / "queries" / "_common.py")
    assert len(forma_a) >= 8, (
        "_common.py so tem a forma com nome intermediario: lista vazia aqui "
        f"significa que o guard perdeu a forma A por inteiro. {forma_a}"
    )
    assert all(seguro for _, _, seguro in forma_a + forma_b)


# --------------------------------------------------------------------------
# Mordidas. Cada uma nomeia a implementacao errada concreta contra a qual fica
# vermelha — teste que passa contra o codigo bom E contra o quebrado nao e
# guard.
# --------------------------------------------------------------------------


@contextmanager
def _modulo(fonte: str) -> Iterator[Path]:
    with tempfile.TemporaryDirectory() as d:
        arquivo = Path(d) / "sintetico.py"
        arquivo.write_text(fonte, encoding="utf-8")
        yield arquivo


_FORMA_A = (
    "def q(ids):\n"
    '    clausula = ", ".join({item})\n'
    '    return f"SELECT x FROM y WHERE ad_group.id IN ({{clausula}})"\n'
)

_FORMA_B = (
    "def q(ids):\n    return f\"SELECT x FROM y WHERE campaign.id IN ({{','.join({item})}})\"\n"
)


@pytest.mark.parametrize(
    ("molde", "forma"), [(_FORMA_A, "A (nome intermediario)"), (_FORMA_B, "B (inline)")]
)
def test_mordida_1_e_2_as_duas_formas_sao_vistas_e_julgadas(molde: str, forma: str) -> None:
    """Cru e ACUSADO, `str(int(x))` e ABSOLVIDO — nas duas formas.

    Falha contra, na forma A: **casador que nao resolve o nome**, que veria
    `{clausula}` como opaco e nunca chegaria ao `join`.

    Falha contra, na forma B: **implementacao que so olhasse `ast.Assign`**,
    que devolveria lista vazia e passaria por vacuidade. Foi essa a cegueira
    que deixou os quatro sitios de `ad_schedule.py`/`assets.py` fora da lista
    original — sem esta metade, uma implementacao so-Assign fica verde.

    As duas metades juntas sao o que distingue o guard de um casador trivial:
    so a primeira e satisfeita por `seguro = False` fixo; so a segunda, por
    `seguro = True` fixo.
    """
    with _modulo(molde.format(item="ids")) as arquivo:
        cru = _joins_em_clausula_in(arquivo)
        assert len(cru) == 1, f"forma {forma}: o sitio tem que ser ENCONTRADO. {cru}"
        assert cru[0][2] is False, f"forma {forma}: `join` cru tem que ser acusado. {cru}"

    with _modulo(molde.format(item="str(int(x)) for x in ids")) as arquivo:
        seguro = _joins_em_clausula_in(arquivo)
        assert len(seguro) == 1, f"forma {forma}: o sitio tem que ser ENCONTRADO. {seguro}"
        assert seguro[0][2] is True, f"forma {forma}: `str(int(x))` absolve. {seguro}"

    with _modulo(molde.format(item="gaql_string_literal(v) for v in ids")) as arquivo:
        texto = _joins_em_clausula_in(arquivo)
        assert texto[0][2] is True, f"forma {forma}: `gaql_string_literal` absolve. {texto}"


def test_mordida_3_join_que_nao_alimenta_um_in_nao_e_acusado() -> None:
    """Falha contra: **casador que aceitasse qualquer `join` do arquivo**.

    Mensagem de erro com `", ".join(nomes)` e o uso mais comum de `join` no
    repo — 73 call-sites em `src/`, dos quais 22 sao clausula `IN`. Acusar os
    outros 51 vira ruido, e guard ruidoso e guard desligado.

    Os tres casos cobrem os tres jeitos de quase-casar: `join` em mensagem sem
    `IN` nenhum, `IN` como palavra sem parentese, e `join` numa OUTRA clausula
    do mesmo GAQL (`WHERE {…}`), que e como quase todo builder do diretorio
    interpola filtro montado.
    """
    mensagem = "def erro(nomes):\n    return f\"campos invalidos: {', '.join(nomes)}\"\n"
    with _modulo(mensagem) as arquivo:
        assert _joins_em_clausula_in(arquivo) == []

    in_sem_parentese = "def erro(nomes):\n    return f\"ids IN uso: {', '.join(nomes)}\"\n"
    with _modulo(in_sem_parentese) as arquivo:
        assert _joins_em_clausula_in(arquivo) == []

    outra_clausula = (
        "def q(filtros):\n    return f\"SELECT x FROM y WHERE {' AND '.join(filtros)}\"\n"
    )
    with _modulo(outra_clausula) as arquivo:
        assert _joins_em_clausula_in(arquivo) == []


def test_mordida_4_nome_reusado_nao_e_absolvido_pela_atribuicao_seguinte() -> None:
    """O caso que a varredura de 2026-09-08 perdeu, e o unico achado desta
    rodada que nao estava no requisito.

    `_resolve_names` (`get_change_history.py`) reusa `ids_clause` para dois
    `IN` diferentes, 15 linhas de distancia. Um resolvedor nome->ultima
    atribuicao ve a SEGUNDA nos dois usos: se a segunda for segura e a
    primeira crua, o guard absolve um sitio vivo sem dizer nada, e a tabela
    de sitios sai com um a menos (foi o que aconteceu — onze linhas para doze
    sitios).

    Falha contra: **resolvedor last-wins**, que devolveria `True` nos dois.
    A segunda metade (`primeira` segura, `segunda` crua) fecha a simetria: um
    resolvedor first-wins erraria ali, e passaria na primeira metade.
    """
    cru_depois_seguro = (
        "def q(a, b):\n"
        '    ids_clause = ",".join(a)\n'
        '    primeira = f"WHERE campaign.id IN ({ids_clause})"\n'
        '    ids_clause = ",".join(str(int(x)) for x in b)\n'
        '    segunda = f"WHERE ad_group.id IN ({ids_clause})"\n'
        "    return primeira + segunda\n"
    )
    with _modulo(cru_depois_seguro) as arquivo:
        achados = _joins_em_clausula_in(arquivo)
        assert [seguro for _, _, seguro in achados] == [False, True], achados

    seguro_depois_cru = (
        "def q(a, b):\n"
        '    ids_clause = ",".join(str(int(x)) for x in a)\n'
        '    primeira = f"WHERE campaign.id IN ({ids_clause})"\n'
        '    ids_clause = ",".join(b)\n'
        '    segunda = f"WHERE ad_group.id IN ({ids_clause})"\n'
        "    return primeira + segunda\n"
    )
    with _modulo(seguro_depois_cru) as arquivo:
        achados = _joins_em_clausula_in(arquivo)
        assert [seguro for _, _, seguro in achados] == [True, False], achados


def test_mordida_5_interpolacao_que_nao_resolve_falha_fechado() -> None:
    """Um helper escondendo a montagem NAO isenta o sitio.

    Falha contra: **implementacao que so registrasse o que resolve para um
    `join`**, deixando de fora tudo o mais. Nao e hipotetico: a primeira
    versao do fix de `ad_schedule.py` nesta rodada extraiu um
    `_ids(campaign_ids)` para nao repetir o idioma tres vezes, e teria
    apagado os tres sitios do escopo do guard de uma vez. Com esta mordida, a
    saida e ensinar o guard, nao esconder o sitio dele.

    O parametro de funcao cobre o mesmo buraco por outro caminho: clausula que
    chega pronta de fora nao tem como ser julgada, e o desconhecido e ofensor.
    """
    helper = 'def q(ids):\n    return f"WHERE campaign.id IN ({_monta(ids)})"\n'
    with _modulo(helper) as arquivo:
        achados = _joins_em_clausula_in(arquivo)
        assert len(achados) == 1 and achados[0][2] is False, achados

    parametro = 'def q(clausula):\n    return f"WHERE campaign.id IN ({clausula})"\n'
    with _modulo(parametro) as arquivo:
        achados = _joins_em_clausula_in(arquivo)
        assert len(achados) == 1 and achados[0][2] is False, achados


def test_mordida_6_o_escopo_e_derivado_e_alcanca_os_dois_diretorios() -> None:
    """Falha contra: **escopo listado** (ou apontado so para `queries/`).

    Cinco dos doze sitios desta rodada moram em `src/mcp/tools/`, nao em
    `src/google_ads/queries/` — inclusive os dois de mutacao. Um guard
    apontado so para o diretorio de queries ficaria verde com eles crus.
    """
    varridos = {h.rel(a) for escopo in _ESCOPOS for a in h.fontes_py(escopo)}
    assert "src/google_ads/queries/ad_schedule.py" in varridos
    assert "src/google_ads/reports.py" in varridos
    assert "src/mcp/tools/update_keyword_bid.py" in varridos
    assert len(varridos) > 100, (
        f"escopo pequeno demais para ser os dois diretorios: {len(varridos)}"
    )
