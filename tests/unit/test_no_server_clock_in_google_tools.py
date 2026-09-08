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

## O que conta como "ler o relogio" (apertado em 2026-09-08)

Ate 07/09 o casador via TRES formas — `datetime.now`, `date.today` e
`datetime.today` — e so quando o objeto era um `ast.Name` com esse nome
literal. Cinco escapavam, todas verdes:

| Forma | Por que escapava |
|---|---|
| `datetime.utcnow()` | `utcnow` nao estava no conjunto |
| `time.time()` | idem |
| `from time import time` -> `time()` | e `ast.Name`, nao `ast.Attribute` |
| `from datetime import datetime as dt` -> `dt.now()` | o nome escrito era `dt` |
| `import datetime as dt` -> `dt.datetime.now()` | `f.value` era `Attribute` |

Nenhuma e hipotetica: `utcnow()` e o que quase todo Python anterior ao 3.12
escreve, `time.time()` e o relogio sem fuso nenhum, e alias de import e o que um
formatador ou um autocomplete produz sozinho. O casador resolve os imports do
modulo antes de perguntar (`h.origens_de_import` + `h.caminho_canonico`) e
compara o par `(objeto, atributo)` do caminho ja canonico.

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

## O escopo ainda e listado a mao, e isso e uma folga MEDIDA

O casador foi apertado em 2026-09-08 (utcnow, time.time, alias de import), mas o
ESCOPO continua sendo uma lista de diretorios e arquivos. Medi o que fica de
fora: 13 arquivos de `src/` leem relogio sem estar sob nenhum dos dois regimes.

Tres ja tem motivo escrito (`FORA_COM_MOTIVO`). Dos dez restantes:

- `src/auth/oauth_state.py`, `panel_session.py`, `meta_oauth.py` e
  `src/governance/rate_limit.py`: `time.time()`/epoch para TTL e bucket de
  quota. Comparam AGORA com um instante absoluto — nao derivam DATA de conta
  nenhuma, entao nao sao F141.
- `src/db/repositories/managers.py`, `src/governance/dry_run.py`,
  `src/web/routes.py`: carimbo de registro e de sessao, idem.
- **`src/mcp/tools/_meta_performance.py`, `meta_get_account_overview.py` e
  `meta_get_performance_breakdown.py`: estes SAO a mesma classe.** Sao os
  quatro sitios do gemeo Meta do F141, que a spec da varredura atribui ao PR 6
  (o inventario Meta ja tem `timezone_name` no banco e ninguem le). Nao foram
  antecipados aqui de proposito — sao trabalho de outra frente, e a excecao
  `meta_*` no topo deste arquivo existe justamente para isso.

**A correcao estrutural e inverter o guard**: varrer `src/` inteiro e exigir que
todo leitor de relogio esteja em `LEITORES_LEGITIMOS` ou em `FORA_COM_MOTIVO`.
Isso troca uma lista de ESCOPO (que esquece o diretorio novo em silencio) por
uma lista de EXCECAO (que obriga a escrever o motivo). Fica para o PR 6, junto
com os quatro sitios Meta — inverter antes de corrigi-los so encheria a lista de
excecao com trabalho ja planejado.
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
    # `datetime.now(_BRT)` numa checagem "conversao nao esta no futuro", com -03:00
    # HARDCODED — o tool inteiro assume BRT e anexa "-03:00" ao que envia ao
    # Google. Nao e predicado de janela (F141); e outra classe: contrato de upload
    # assumindo um fuso que 2 das 25 contas nao tem. Finding proprio (F146).
    "import_offline_conversions.py",
    # `datetime.now(UTC).date()` compoe o PREFIXO do objeto no GCS
    # (`<prefixo>/<data>/<tabela>.csv.gz`). Nao e predicado de janela de conta:
    # nenhuma conta anunciante participa da decisao, e o dump e do banco inteiro.
    # UTC aqui e a escolha certa — nome de objeto de storage precisa ser estavel
    # e comparavel entre runs, nao relativo ao fuso de um cliente.
    "backup.py",
}

# O par `(objeto, atributo)` que fecha o caminho, DEPOIS de resolver alias.
# Cinco formas escapavam do conjunto antigo — nenhuma hipotetica: `utcnow()` e o
# que quase todo Python anterior a 3.12 escreve, `time.time()` e o relogio sem
# fuso nenhum, e alias de import e o que um autocomplete produz sozinho.
#
# `time.monotonic` e `time.perf_counter` NAO entram, e a ausencia e deliberada:
# nao respondem "que dia e hoje" — sao contador de duracao, e o escopo deste
# guard tem QUATRO tools vivas que os usam pra medir `duration_ms`
# (`get_my_audit_log`, `list_my_accounts`, `validate_gaql`,
# `get_my_rate_limit_status`). Poe-los aqui trocaria o guard por uma lista de
# excecao com quatro nomes no dia seguinte.
_RELOGIO = {
    ("datetime", "now"),
    ("datetime", "today"),
    ("datetime", "utcnow"),
    ("date", "today"),
    ("time", "time"),
}


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


def _nos_de_relogio(arvore: ast.Module) -> list[ast.Call]:
    """Chamadas de relogio de parede, com o alias do import ja resolvido.

    Recebe a ARVORE, nao o texto: os dois consumidores abaixo precisam falar da
    MESMA arvore para poderem comparar nos por identidade (reparsear devolveria
    objetos novos, e o cruzamento sairia vazio em silencio — foi o primeiro
    defeito desta implementacao, pego pelo proprio teste de mordida). Agora ha
    uma segunda razao: os imports do MODULO decidem o que cada nome significa,
    entao a unidade tem que ser o modulo inteiro, nunca um no solto.

    **Por que o casamento e o SUFIXO de dois segmentos, e nao o caminho inteiro.**
    O mesmo simbolo se escreve com 1, 2 ou 3 segmentos conforme o import:
    `datetime.utcnow()` (com `from datetime import datetime`),
    `datetime.datetime.utcnow()` (com `import datetime`), `dt.utcnow()` (com
    alias). Exigir o caminho canonico completo obrigaria o casador a ter visto o
    import — e um trecho sem import nenhum, que e como as mordidas exercitam a
    forma, ficaria de fora. O par `(objeto, atributo)` e o que sobrevive a todas
    as formas.

    **Erra ACUSANDO, e isso e escolhido.** O sufixo faz `qualquer.date.today()`
    entrar, mesmo que `qualquer` nao seja o modulo `datetime`. Este guard e
    POSITIVO — procura o que NAO pode existir —, e a nota de
    `funcoes_chamadas_de_src` no harness diz que nesse sentido a folga erra
    ABSOLVENDO CALADO, que e o modo de falha caro. Falso positivo aqui aparece
    vermelho e alguem le; falso negativo e um `hoje` de servidor em producao que
    so mente das 21h a meia-noite locais. Nao ha nenhum hoje no escopo (medido
    2026-09-08), e se aparecer a resposta e nomea-lo, nao afrouxar o sufixo.
    """
    achados: list[ast.Call] = []
    origens = h.origens_de_import(arvore)
    for node in ast.walk(arvore):
        if not isinstance(node, ast.Call):
            continue
        caminho = h.caminho_canonico(node.func, origens)
        if caminho is None:
            continue
        partes = caminho.split(".")
        if len(partes) >= 2 and (partes[-2], partes[-1]) in _RELOGIO:
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


def test_o_guard_ve_utcnow_time_e_alias_de_import() -> None:
    """As cinco formas que o casador antigo deixava passar.

    Cada uma e um `hoje` do SERVIDOR entrando em caminho de conta pela porta que
    ninguem fechou — e o sintoma e o mesmo do F141: erra so das 21h a meia-noite
    locais, que e quando ninguem esta testando.

    Falha contra: **o casador anterior a 2026-09-08** (`ast.Attribute` com
    `.value` `ast.Name`, sobre `{("datetime","now"), ("date","today"),
    ("datetime","today")}`). Medido naquele dia, com aquele casador copiado
    verbatim: as CINCO devolviam `[]` — verde, sem uma palavra.
    """
    # `utcnow` nao estava no conjunto proibido
    assert _chamadas_de_relogio("x = datetime.utcnow()") == [1]
    # `time.time` idem — relogio de parede, e sem fuso nenhum
    assert _chamadas_de_relogio("import time\nx = time.time()") == [2]
    # `ast.Name`: o casador antigo so olhava `ast.Attribute`
    assert _chamadas_de_relogio("from time import time\nx = time()") == [2]
    # alias da CLASSE: `f.value.id` era "dt", que nao estava no conjunto
    assert _chamadas_de_relogio("from datetime import datetime as dt\nx = dt.now(UTC)") == [2]
    # alias do MODULO: `f.value` e `Attribute`, e o casador antigo exigia `Name`
    assert _chamadas_de_relogio("import datetime as dt\nx = dt.datetime.now()") == [2]


def test_o_guard_apertado_nao_passa_a_acusar_o_inocente() -> None:
    """Controle das duas metades que o aperto poderia ter atropelado.

    Falha contra: **casador que perguntasse so pelo atributo** (`.time`,
    `.now`), e contra **quem tratasse `h.nomes_locais` como prova de vinculo** —
    aquela funcao devolve o alvo mesmo sem import nenhum, entao um parametro
    `def f(time)` chamado como `time()` viraria ofensor. E por isso que este
    guard usa `origens_de_import`, que so liga nome que um `import` de fato
    ligou; o motivo esta escrito na docstring dela, no harness.

    A segunda metade e viva, nao hipotetica: `time.monotonic()` esta em QUATRO
    tools dentro do escopo estrito (`get_my_audit_log`, `list_my_accounts`,
    `validate_gaql`, `get_my_rate_limit_status`) medindo `duration_ms`. Se
    contasse como relogio, o guard nasceria vermelho e o conserto seria uma
    lista de excecao com quatro nomes — guard virando lista, de novo.
    """
    assert _chamadas_de_relogio("def f(time):\n    return time.strftime('%Y')") == []
    assert _chamadas_de_relogio("def f(time):\n    return time()") == []
    assert _chamadas_de_relogio("import time\nx = time.monotonic()") == []
    assert _chamadas_de_relogio("import time\nx = time.perf_counter()") == []
    # construtor de data, nao leitura de relogio
    assert _chamadas_de_relogio("from datetime import date\nx = date(2026, 9, 8)") == []


def test_o_aperto_nao_perdeu_as_formas_que_o_casador_antigo_ja_via() -> None:
    """As tres originais seguem pegas — com o import a vista e sem ele.

    Falha contra: **resolvedor que exigisse import** para canonizar o caminho.
    Essa e a tentacao natural depois de resolver alias (comparar o caminho
    canonico inteiro, `datetime.datetime.now`), e ela absolveria calada todo
    trecho onde o import nao esta no pedaco lido — inclusive as mordidas acima,
    que e como o aperto se autoenganaria.
    """
    com_import = "from datetime import UTC, date, datetime\n"
    assert _chamadas_de_relogio(com_import + "x = datetime.now(UTC)") == [2]
    assert _chamadas_de_relogio(com_import + "x = date.today()") == [2]
    assert _chamadas_de_relogio(com_import + "x = datetime.today()") == [2]
    assert _chamadas_de_relogio("x = date.today()") == [1]
    assert _chamadas_de_relogio("import datetime\nx = datetime.datetime.today()") == [2]


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
