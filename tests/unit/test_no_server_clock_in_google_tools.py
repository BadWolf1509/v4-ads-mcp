"""F141 guard: caminho de conta nao le o relogio do servidor — `hoje` vem da conta.

A invariante e "um `hoje` por request (ou por execucao de job), no fuso da
conta". Antes do fix ela era violada em TRES lugares dentro do mesmo caminho
(`parse_date_range`, o clamp F23 e a sonda de fronteira em `get_change_history`,
mais o `LAST_2_DAYS` em `detect_drift`), e o proximo `datetime.now(UTC).date()`
que alguem escrever num tool novo reabre a classe em silencio — o bug so aparece
das 21h a meia-noite locais, que e quando ninguem esta testando.

Por que AST e nao grep: comentarios e docstrings destes arquivos CITAM o
padrao proibido para explicar o fix (modo de falha 1 de guards-que-nao-cobrem:
o guard casa a propria prosa). O AST ve so chamadas.

## Os dois regimes

O escopo se divide em dois, e a diferenca e o que este guard afirma:

- **`_arquivos_sem_relogio()`** — nao pode ler o relogio de jeito nenhum.
- **`LEITORES_LEGITIMOS`** — pode, e SO na forma
  `now if now is not None else datetime.now(UTC)`: default injetavel de um
  parametro que o chamador normalmente fornece. Um `datetime.now()` solto
  nesses arquivos e tao F141 quanto num tool.

Excecoes, cada uma com motivo — NAO e lista de alvos, e lista do que fica de
fora e por que:
- `meta_*` / `_meta_*` **em `src/mcp/tools/`**: contas Meta tem fuso proprio no
  inventario Meta; a mesma classe de bug la e outro finding, com outro fix. O
  filtro vale so para o diretorio de tools — em `src/jobs/` um arquivo
  `meta_*` entra normalmente, senao um job Meta novo escaparia pelo NOME.
- `get_my_rate_limit_status`: o bucket de quota E em UTC por desenho (mesma
  chave que `governance/rate_limit._today`); o campo se chama `date_utc`.
- `import_offline_conversions`: ver F146 abaixo.
- `backup.py`: ver o comentario na propria entrada.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.unit import _guard_harness as h

TOOLS = (
    h.SRC / "mcp" / "tools"
)  # absoluto, derivado de __file__ (harness); relativo via cwd zerava o glob
# `src/jobs/` entrou em 2026-09-07 (M5 da revisao final da branch
# pr2/reconciliacao-idempotente). Os dois jobs de resync liam o relogio desde o
# C4 e ficavam fora do guard porque NINGUEM OS LISTOU — que e a mesma falha um
# andar acima. Varrer o diretorio inteiro faz o job NOVO entrar sozinho; listar
# mais dois nomes repetiria o defeito.
JOBS = h.SRC / "jobs"
PRIMITIVOS = [
    h.SRC / "google_ads" / "queries" / "_common.py",
    h.SRC / "google_ads" / "change_freshness.py",
    # `account_today` SAIU do `_common.py` em 2026-09-06 (mora em `src/clock.py`,
    # neutro entre os dois provedores). O guard segue o CODIGO, nao o caminho:
    # sem esta linha, a funcao que resolve `hoje` sairia do escopo do guard so
    # por ter mudado de arquivo — e o guard passaria verde olhando o lugar de
    # onde ela saiu. Cobre tambem o consumo Meta, que herda o mesmo primitivo.
    h.SRC / "clock.py",
    # Os DOIS planejadores entraram em 2026-09-06: desde o C4 eles resolvem
    # `hoje` no fuso da conta para decidir se a ausencia desta execucao ja esta
    # em `missed_syncs`. Recebem o instante (`now`) e nao leem relogio — e e
    # justamente isso que esta lista prende: um `now: datetime | None = None`
    # com `datetime.now(UTC)` de default poria o F141 DENTRO da decisao que
    # desativa conta e revoga grant, na janela das 21h a meia-noite locais. O
    # gemeo Meta entra pela mesma razao que `clock.py` (o consumo Meta herda o
    # mesmo primitivo), apesar da excecao geral a arquivos `meta_*`, que vale
    # para os tools de `src/mcp/tools/`.
    h.SRC / "google_ads" / "reconcile.py",
    h.SRC / "meta_ads" / "reconcile.py",
]

# Podem ler o relogio, e SO como default injetavel. Nao sao excecao ao guard:
# sao o segundo regime dele, com teste proprio (`test_os_leitores_legitimos_...`).
LEITORES_LEGITIMOS = [
    # O ponto de I/O do fix do F141 no caminho de request.
    h.SRC / "google_ads" / "account_clock.py",
    # Os dois jobs de resync (C4, 2026-09-06): o relogio aqui da um INSTANTE,
    # lido uma vez por execucao; toda derivacao de DATA passa por
    # `src.clock.account_today` com o fuso de cada conta. Injetavel porque so
    # assim o teste consegue um instante em que UTC e a conta discordam — a
    # diferenca que `freezegun` nao representa. Ate 07/09 os dois ficavam fora
    # do guard sem excecao escrita, e a prosa dizia que `account_clock.py` era
    # "o unico leitor legitimo", o que este PR tornou falso.
    h.SRC / "jobs" / "account_resync.py",
    h.SRC / "jobs" / "meta_resync.py",
]

FORA_COM_MOTIVO = {
    # bucket de quota em UTC por desenho (mesma chave de governance/rate_limit)
    "get_my_rate_limit_status.py",
    # `datetime.now(tz)` numa checagem "a conversao nao esta no futuro / nao
    # passou de 90 dias", com `tz` = o FUSO DA CONTA, resolvido por
    # `resolve_account_zone` (F146, fechado). Nao e predicado de janela de
    # relatorio (F141): e a comparacao entre AGORA e um instante que o gestor
    # digitou, e ela precisa de um agora. O que o F146 tirou daqui foi o offset
    # HARDCODADO; o R1-I6 (2026-09-07) tirou o segundo uso, que anunciava no
    # preview o offset de HOJE em vez do offset da DATA de cada conversao —
    # agora as duas pontas chamam `conversions.utc_offset`.
    "import_offline_conversions.py",
    # `datetime.now(UTC).date()` compoe o PREFIXO do objeto no GCS
    # (`<prefixo>/<data>/<tabela>.csv.gz`). Nao e predicado de janela de conta:
    # nenhuma conta anunciante participa da decisao, e o dump e do banco inteiro.
    # UTC aqui e a escolha certa — nome de objeto de storage precisa ser estavel
    # e comparavel entre runs, nao relativo ao fuso de um cliente.
    "backup.py",
}

_RELOGIO = {("datetime", "now"), ("date", "today"), ("datetime", "today")}


def _arquivos_sem_relogio() -> list[Path]:
    """Escopo do regime estrito: nem uma leitura de relogio e admitida."""
    legitimos = set(LEITORES_LEGITIMOS)
    tools = [
        p
        for p in h.fontes_py(TOOLS)
        if not p.name.startswith(("meta_", "_meta_")) and p.name not in FORA_COM_MOTIVO
    ]
    jobs = [p for p in h.fontes_py(JOBS) if p.name not in FORA_COM_MOTIVO and p not in legitimos]
    return tools + jobs + PRIMITIVOS


def _nos_de_relogio(arvore: ast.AST) -> list[ast.Call]:
    """Nos `datetime.now(...)`, `date.today()` ou `datetime.today()` — so chamadas.

    Recebe a ARVORE, nao o texto: os dois consumidores abaixo precisam falar da
    MESMA arvore para poderem comparar nos por identidade (reparsear devolveria
    objetos novos, e o cruzamento sairia vazio em silencio — foi o primeiro
    defeito desta implementacao, pego pelo proprio teste de mordida).
    """
    achados: list[ast.Call] = []
    for node in ast.walk(arvore):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if (
            isinstance(f, ast.Attribute)
            and isinstance(f.value, ast.Name)
            and (f.value.id, f.attr) in _RELOGIO
        ):
            achados.append(node)
    return achados


def _chamadas_de_relogio(src: str) -> list[int]:
    return [n.lineno for n in _nos_de_relogio(ast.parse(src))]


def _default_injetavel(node: ast.AST) -> bool:
    """`X if X is not None else <...>` — a unica forma que admite ler o relogio.

    Exige que o corpo do ternario seja o MESMO nome testado: `a if b is not None
    else datetime.now(UTC)` nao e default injetavel, e um relogio disfarcado.
    """
    if not isinstance(node, ast.IfExp):
        return False
    teste = node.test
    return (
        isinstance(teste, ast.Compare)
        and len(teste.ops) == 1
        and isinstance(teste.ops[0], ast.IsNot)
        and len(teste.comparators) == 1
        and isinstance(teste.comparators[0], ast.Constant)
        and teste.comparators[0].value is None
        and isinstance(teste.left, ast.Name)
        and isinstance(node.body, ast.Name)
        and node.body.id == teste.left.id
    )


def _relogio_fora_do_default_injetavel(src: str) -> list[int]:
    """Leituras de relogio que NAO estao no `else` de um default injetavel.

    E a diferenca entre este guard e o que estava aqui antes, que aceitava
    `_chamadas_de_relogio(src) == [] or "<idioma>" in src`: bastava o idioma
    aparecer UMA vez para qualquer outra leitura do arquivo passar junto. Uma
    assercao que nao distingue codigo bom de quebrado nao e guard.
    """
    arvore = ast.parse(src)
    permitidas: set[int] = set()
    for node in ast.walk(arvore):
        if _default_injetavel(node):
            assert isinstance(node, ast.IfExp)
            permitidas.update(id(c) for c in ast.walk(node.orelse) if isinstance(c, ast.Call))
    return [n.lineno for n in _nos_de_relogio(arvore) if id(n) not in permitidas]


def test_nenhum_caminho_de_conta_le_o_relogio_do_servidor() -> None:
    ofensores = {
        str(p): _chamadas_de_relogio(p.read_text(encoding="utf-8")) for p in _arquivos_sem_relogio()
    }
    ofensores = {k: v for k, v in ofensores.items() if v}
    assert ofensores == {}, (
        "relogio do servidor em caminho de conta (F141) — `hoje` tem que vir de "
        f"`resolve_account_today`/`account_today`: {ofensores}"
    )


def test_os_leitores_legitimos_so_leem_o_relogio_como_default_injetavel() -> None:
    """Os TRES que podem ler: `account_clock` e os dois jobs de resync.

    Sao tres desde o C4 (2026-09-06); a prosa deste arquivo dizia "o unico" ate
    07/09. Cada um pode ler o relogio uma vez, e SO no `else` de
    `now if now is not None else ...` — o instante ainda entra por parametro em
    todo caminho testado, e toda DATA derivada dele passa por `account_today`
    com o fuso da conta.

    Se este teste falhar porque um dos modulos deixou de ler o relogio, tudo bem
    — tire-o de `LEITORES_LEGITIMOS` e ele passa a ser coberto pelo regime
    estrito. Se falhar porque apareceu leitura fora do idioma, e o F141 voltando.
    """
    ofensores = {
        str(p): _relogio_fora_do_default_injetavel(p.read_text(encoding="utf-8"))
        for p in LEITORES_LEGITIMOS
    }
    ofensores = {k: v for k, v in ofensores.items() if v}
    assert ofensores == {}, (
        "leitura de relogio fora do default injetavel `now if now is not None "
        f"else datetime.now(UTC)`: {ofensores}"
    )


def test_cada_leitor_legitimo_de_fato_le_o_relogio() -> None:
    """Contraprova: sem ela, `LEITORES_LEGITIMOS` viraria lista de isencao.

    Um arquivo que nao le relogio nenhum nao precisa estar aqui — precisa estar
    no regime estrito. Esta assercao e o que impede a lista de crescer com nomes
    postos "por seguranca", que e como uma lista de excecao vira coadora.
    """
    sem_relogio = [
        str(p)
        for p in LEITORES_LEGITIMOS
        if not _chamadas_de_relogio(p.read_text(encoding="utf-8"))
    ]
    assert sem_relogio == [], (
        "estes arquivos nao leem relogio nenhum, entao nao sao 'leitores "
        f"legitimos' — mova-os para o regime estrito: {sem_relogio}"
    )


def test_o_guard_enxerga_uma_chamada_de_verdade() -> None:
    """Guard que nunca viu vermelho nao e guard: prova que o AST casa a forma proibida."""
    assert _chamadas_de_relogio("x = datetime.now(UTC).date()") == [1]
    assert _chamadas_de_relogio("# datetime.now(UTC).date() so no comentario") == []
    assert _chamadas_de_relogio('"""datetime.now(UTC) so na docstring"""') == []


def test_o_guard_do_default_injetavel_distingue_as_duas_formas() -> None:
    """A assercao antiga passava nos quatro casos abaixo; esta so passa no 1o.

    O caso 2 e o que importa: o idioma legitimo PRESENTE no arquivo nao pode
    absolver uma segunda leitura solta.
    """
    idioma = "agora = now if now is not None else datetime.now(UTC)"
    assert _relogio_fora_do_default_injetavel(idioma) == []
    assert _relogio_fora_do_default_injetavel(idioma + "\nhoje = date.today()") == [2]
    # nome trocado no corpo do ternario: nao e default injetavel, e relogio disfarcado
    assert _relogio_fora_do_default_injetavel(
        "agora = outro if now is not None else datetime.now(UTC)"
    ) == [1]
    # ternario sem `is not None`: idem
    assert _relogio_fora_do_default_injetavel("agora = now if now else datetime.now(UTC)") == [1]


def test_o_guard_do_relogio_recusa_escopo_vazio() -> None:
    """Antes do harness, `Path("src/mcp/tools")` relativo devolvia 0 arquivos de
    qualquer cwd que nao fosse a raiz, e o guard passava sem olhar nada."""
    import pytest

    with pytest.raises(h.EscopoVazioError):
        h.fontes_py(h.SRC / "mcp" / "tools" / "nao_existe")
