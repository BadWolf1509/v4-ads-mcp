"""§3.2, a metade que o guard da declaracao nao enxerga: o teto pedido ao
Google e `limit + 1`.

`test_declaracao_de_truncamento` le o RETORNO da tool; nao le a QUERY. Uma
tool que chama `aplicar_limite` corretamente, declara `truncated` e pede
`LIMIT {limit}` passa naquele guard e mente `false` PARA SEMPRE — com a
consulta cortada em `limite`, `len(linhas) > limite` e falso por construcao.
O detector nasce morto e nada fica vermelho. Este guard fecha esse buraco.

**O escopo e derivado, nao listado.** Sao as funcoes de
`src/google_ads/queries/` que uma tool com `limit` no schema de fato CHAMA —
mesma derivacao (registry) e mesmo salto (`funcoes_chamadas_de_src`) do guard
irmao, por `h.tools_com_limite()`. Builder novo entra sozinho no dia em que
uma tool com `limit` passar a chama-lo.

Derivar do CONSUMIDOR, e nao varrer o diretorio inteiro, e o que mantem a
invariante colada ao que ela afirma: `client_report.py` pede `LIMIT {top_n}`
para `get_top_keywords_creatives`, que declara `top_n` (nao `limit`),
reordena no cliente e nao promete `truncated` nenhum. Exigir a sentinela la
seria cobrar a invariante de quem nao a tem — e, pior, faria a linha extra
vazar pro gestor no caminho `metric == "cost"`, que nao corta depois.
"""

from __future__ import annotations

import ast
import re
import tempfile
from pathlib import Path

from tests.unit import _guard_harness as h

_QUERIES = (h.SRC / "google_ads" / "queries").resolve()

# Pisos de tamanho, medidos em 2026-09-07. Sao OBSERVACAO, nao teto — builder
# novo so faz subir. Existem porque `EscopoVazioError` so dispara com ZERO:
# um scanner de f-string que parasse de casar devolveria "nenhum ofensor" e
# ficaria verde para sempre, que e a forma mais silenciosa de um guard morrer.
_PISO_DE_FUNCOES = 20  # observadas 33
_PISO_DE_LIMITES = 8  # observados 12

_LIMIT_ANTES_DA_CHAVE = re.compile(r"\bLIMIT\s+$", re.IGNORECASE)


def _funcoes_de_query_de_tool_com_limite() -> list[tuple[Path, ast.AST]]:
    """As funcoes de `src/google_ads/queries/` alcancadas por tool com `limit`.

    Um salto, igual ao guard irmao. Duas tools que chamem o mesmo builder o
    trazem uma vez so (`dict` keyed por arquivo+nome).
    """
    achadas: dict[tuple[str, str], tuple[Path, ast.AST]] = {}
    for _, arquivo, _handler in h.tools_com_limite():
        for helper, fn in h.funcoes_chamadas_de_src(arquivo):
            resolvido = helper.resolve()
            if _QUERIES not in resolvido.parents:
                continue
            achadas[(str(resolvido), fn.name)] = (resolvido, fn)
    if len(achadas) < _PISO_DE_FUNCOES:
        raise h.EscopoVazioError(
            f"so {len(achadas)} funcoes de queries/ alcancadas por tool com "
            f"`limit` (piso: {_PISO_DE_FUNCOES}, observadas 33 em 2026-09-07). "
            "Ou o registry nao carregou, ou o resolvedor de saltos parou de "
            "casar — nos dois casos o guard estaria varrendo uma fracao da "
            "superficie sem dizer nada."
        )
    return [achadas[k] for k in sorted(achadas)]


def _limites_interpolados(no: ast.AST) -> list[tuple[ast.expr, int]]:
    """`(expressao, linha)` de cada `LIMIT {…}` de f-string dentro de `no`.

    Casa pelo TEXTO que precede a chave dentro do proprio `JoinedStr` — e nao
    por leitura de linha do arquivo — porque a clausula quase sempre nasce de
    um bloco `f\"\"\"…\"\"\"` de varias linhas, onde `LIMIT` e a chave estao na
    mesma parte constante mas nao na mesma linha fisica de nenhum regex de
    texto cru. `LIMIT 101` e `LIMIT 10000` (literais) nao aparecem aqui de
    proposito: nao ha o que checar num teto que ja e constante.
    """
    achados: list[tuple[ast.expr, int]] = []
    for sub in ast.walk(no):
        if not isinstance(sub, ast.JoinedStr):
            continue
        anterior = ""
        for parte in sub.values:
            if isinstance(parte, ast.Constant) and isinstance(parte.value, str):
                anterior = parte.value
            elif isinstance(parte, ast.FormattedValue):
                if _LIMIT_ANTES_DA_CHAVE.search(anterior):
                    achados.append((parte.value, getattr(parte, "lineno", sub.lineno)))
                anterior = ""
    return achados


def _pede_a_sentinela(expressao: ast.expr) -> bool:
    """`<qualquer coisa> + 1`, e so isso.

    Nao aceita `1 + limit` de proposito: a forma canonica no repo e
    `{limit + 1}` (`ad_schedule`, `overview`, `recommendations` desde que
    ganharam `truncated`), e reconhecer variantes so aumentaria a superficie
    do casador sem cobrir nenhum caso vivo. Se um builder novo escrever a
    soma ao contrario, o guard fica vermelho e a resposta certa e padronizar
    a escrita, nao afrouxar o casador.
    """
    return (
        isinstance(expressao, ast.BinOp)
        and isinstance(expressao.op, ast.Add)
        and isinstance(expressao.right, ast.Constant)
        and expressao.right.value == 1
    )


def test_todo_builder_de_tool_com_limite_pede_a_linha_sentinela() -> None:
    """A propriedade: `LIMIT {limit}` nao existe em builder de tool com `limit`.

    Ofensor aqui nao e estilo: e um `truncated` que devolve `false` para
    sempre, que e pior que campo nenhum — o gestor le "nao cortei" de uma
    resposta cortada.
    """
    ofensores: list[str] = []
    examinados = 0
    for arquivo, fn in _funcoes_de_query_de_tool_com_limite():
        nome = getattr(fn, "name", "?")
        for expressao, linha in _limites_interpolados(fn):
            examinados += 1
            if not _pede_a_sentinela(expressao):
                ofensores.append(
                    f"{h.rel(arquivo)}::{nome}:{linha} -> LIMIT {{{ast.unparse(expressao)}}}"
                )
    if examinados < _PISO_DE_LIMITES:
        raise h.EscopoVazioError(
            f"so {examinados} clausulas `LIMIT {{…}}` examinadas (piso: "
            f"{_PISO_DE_LIMITES}, observadas 12 em 2026-09-07). O casador de "
            "f-string parou de enxergar a clausula, e um guard que nao acha "
            "nada para checar passa por vacuidade."
        )
    assert ofensores == [], (
        "builder de tool com `limit` pedindo o teto exato ao Google. Sem a "
        "linha sentinela, `aplicar_limite` compara `len(linhas) > limite` "
        "contra uma lista cortada em `limite` e devolve `truncated: false` "
        "sempre — o detector nasce morto:\n  " + "\n  ".join(ofensores)
    )


# --------------------------------------------------------------------------
# Mordidas. Cada uma nomeia a implementacao errada concreta contra a qual fica
# vermelha — teste que passa contra o codigo bom E contra o quebrado nao e
# guard.
# --------------------------------------------------------------------------


def _fn(fonte: str) -> ast.AST:
    return h.funcoes(ast.parse(fonte))[0]


def test_mordida_a_forma_sem_sentinela_e_acusada() -> None:
    """Falha contra: **casador que nao le a expressao** (que aceitasse
    qualquer interpolacao apos `LIMIT`). E a forma exata das 8 devedoras.
    """
    fn = _fn('def q(limit):\n    return f"""\n        FROM x\n        LIMIT {limit}\n    """\n')
    achados = _limites_interpolados(fn)
    assert len(achados) == 1, "controle: a clausula tem que ser encontrada"
    assert not _pede_a_sentinela(achados[0][0])


def test_mordida_a_forma_com_sentinela_e_absolvida() -> None:
    """Falha contra: **casador cego a `+ 1`** (que acusasse todo mundo). Sem
    esta metade, um guard que devolvesse `False` fixo passaria na mordida de
    cima e cobraria decoracao de quem ja esta certo.
    """
    fn = _fn('def q(limit):\n    return f"""\n        FROM x\n        LIMIT {limit + 1}\n    """\n')
    achados = _limites_interpolados(fn)
    assert len(achados) == 1, "controle: a clausula tem que ser encontrada"
    assert _pede_a_sentinela(achados[0][0])


def test_mordida_limit_literal_nao_entra_no_escopo() -> None:
    """`LIMIT 101` / `LIMIT 10000` sao tetos constantes (sentinela ja embutida
    no `bulk_pause`, cap duro da API no `change_event`). Falha contra:
    **casador que procurasse a palavra `LIMIT` no texto** em vez da
    interpolacao — esse acusaria os dois e forcaria uma excecao por nome, que
    e como guard vira lista.
    """
    fn = _fn('def q():\n    return f"""\n        FROM x\n        LIMIT 101\n    """\n')
    assert _limites_interpolados(fn) == []


def test_mordida_interpolacao_fora_do_limit_nao_entra() -> None:
    """Falha contra: **casador que aceitasse qualquer `{…}` no f-string**.
    `WHERE`/`ORDER BY` interpolam clausula montada (`{status_clause}`,
    `{gaql_date_clause(...)}`) em quase todo builder do diretorio; exigir
    `+ 1` delas deixaria o guard permanentemente vermelho por ruido.
    """
    fn = _fn(
        'def q(where, limit):\n    return f"""\n        FROM x\n'
        '        WHERE {where}\n        ORDER BY {limit}\n    """\n'
    )
    assert _limites_interpolados(fn) == []


def test_mordida_o_escopo_ignora_o_que_nao_e_query() -> None:
    """Falha contra: **escopo que varresse `src/` inteiro** em vez de
    `src/google_ads/queries/`. O filtro e por diretorio; um helper com
    `LIMIT {n}` fora dele (SQL do Postgres em `src/db/`, por exemplo) nao e
    GAQL e nao tem nada a ver com esta invariante.
    """
    with tempfile.TemporaryDirectory() as d:
        fora = Path(d) / "fora.py"
        fora.write_text('def q(n):\n    return f"LIMIT {n}"\n', encoding="utf-8")
        assert _QUERIES not in fora.resolve().parents


def test_mordida_o_escopo_alcanca_de_fato_os_builders() -> None:
    """Controle positivo do escopo: as funcoes alcancadas sao mesmo de
    `queries/`, e entre elas esta o builder que MAIS tools compartilham.
    Falha contra: **resolvedor de saltos quebrado** que devolvesse lista
    vazia — o `_PISO_DE_FUNCOES` ja pega o zero, mas nao diria que o que
    sobrou e a coisa certa.
    """
    alcancadas = _funcoes_de_query_de_tool_com_limite()
    assert all(_QUERIES in arq.parents for arq, _ in alcancadas)
    nomes = {getattr(fn, "name", "") for _, fn in alcancadas}
    assert {"campaign_performance_query", "change_history_query"} <= nomes
