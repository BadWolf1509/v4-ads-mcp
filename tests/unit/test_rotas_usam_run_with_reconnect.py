"""Task 6 (PR 5, 2026-09-17): leitura idempotente do painel passa por
`run_with_reconnect` (F76/F77) — a mesma reincidência que `test_hot_reads_
reconnect.py` já cobre em `src/web/deps.py` e nos gates MCP, agora no CORPO
das rotas do painel (`src/web/routes/*.py`), que tinha ficado de fora: 36
`pool.acquire()` crus medidos, zero `run_with_reconnect`.

asyncpg NÃO faz pre-ping. Cloud Run mantém conexões ociosas, o Supabase fecha
o socket, e o pool INTEIRO morre — não uma conexão. A primeira query depois
disso estoura na preparação do statement. Pra leitura idempotente isso é um
retry de graça (`run_with_reconnect` reabre numa conexão fresca); pra ESCRITA
seria um retry cego que pode duplicar a mutação (F91) — por isso este guard
só cobra o wrapper de quem PROVADAMENTE só lê, nunca de quem escreve.

## O casador

Acusa `async with pool.acquire() as conn:` (ou `..., conn.transaction():` —
o lado do acquire continua cru) cujo BLOCO — o corpo do próprio `with`, não a
função inteira — não tem nenhuma marca de escrita:

1. direta: chamada `.execute(`/`.executemany(`, OU um literal string que
   COMEÇA (não "contém") com INSERT/UPDATE/DELETE, case-insensitive;
2. delegada a UM salto em `src.*`: o bloco chama uma função — resolvida do
   jeito que `h.funcoes_chamadas_de_src` resolve import (`from src.db.
   repositories import x` ou `import ...; x.f()`) — cujo PRÓPRIO corpo tem a
   marca direta acima.

A unidade é o BLOCO, não a função. `sessions_revoke` (sessions.py) tem DOIS
`pool.acquire()`: o primeiro lê-e-escreve (não entra — F91), o segundo só
relê a lista pro fragmento HTMX depois que a escrita já commitou (site
independente, entra). Classificar a função inteira como "escreve" absolveria
o segundo site em silêncio.

## Os jeitos catalogados em que esta heurística erra (aceitos, não corrigidos)

- **Falso negativo "começa com"**: `SELECT ... FOR UPDATE` tem "UPDATE" no
  meio da frase, mas começa com SELECT — o casador não acusa (trataria como
  leitura). Nenhuma query deste formato existe em `src/web/routes` hoje
  (conferido); se aparecer, este guard não a vê. "Começa com", não
  "contém", é deliberado — ver `_tem_marca_de_escrita_direta`.
- **Falso negativo de constante**: SQL cru guardado num nome
  (`_QUERY = "UPDATE ..."; conn.execute(_QUERY)`) não tem o literal INLINE
  no corpo do bloco — o casador não segue o nome até a constante. Não existe
  esse padrão em `src/web/routes` hoje.
- **Resolução de UM salto, não transitiva**: se uma função só escrevesse
  através de DOIS saltos (`rota -> helper_a -> helper_b -> conn.execute`),
  este casador não veria — `h.funcoes_chamadas_de_src` documenta o mesmo
  limite pra quem ele resolve. Medido contra o repo real em 2026-09-17: toda
  função de `src/db/repositories/*` que as rotas do painel chamam grava com
  `.execute(`/`.executemany(` no PRÓPRIO corpo (script ad-hoc, ast.walk sobre
  os 8 repositórios que as rotas do painel importam) — 1 salto sempre basta
  hoje. Sem esse salto, as 12 rotas transacionais da Task 5 (que têm que
  ficar de fora — já resolvidas lá) e `accounts_revoke_connection` (lê-então-
  escreve sem transação) pareceriam "só leitura" pro casador raso, e este
  guard cobraria `run_with_reconnect` de quem escreve — o dano que o brief da
  Task 6 avisa ser PIOR que não converter nada.

## A exceção que não é sobre escrita: geradores de streaming

`audit.py::audit_export_csv` e `admin_audit.py::admin_audit_export_csv` abrem
`pool.acquire()` dentro de uma função `async def` ANINHADA (`stream`) que é
um GERADOR — `yield`, consumida como `StreamingResponse`. Mesmo sendo leitura
pura, não entra: `run_with_reconnect` espera um `Callable` que devolve um
valor de UMA VEZ (`Awaitable[T]`), não um gerador que fica vivo por todo o
streaming HTTP — um retry no meio reemitiria bytes já entregues ao cliente.
Ortogonal ao F58 (que já protege o cursor de `export_csv_rows` com a própria
`conn.transaction()`): aqui o problema não é ausência de transação, é o
`yield`. Ver `_e_gerador`.
"""

import ast
from pathlib import Path

from tests.unit import _guard_harness as h

_ROTAS = h.SRC / "web" / "routes"
_PREFIXOS_DE_ESCRITA = ("INSERT", "UPDATE", "DELETE")


def _tem_marca_de_escrita_direta(no: ast.AST) -> bool:
    """True se a subárvore de `no` chama `.execute(`/`.executemany(`, OU tem
    um literal string (`Constant`, ou `JoinedStr` pelo primeiro pedaço quando
    ele é texto puro) que, depois de `strip()`, COMEÇA com INSERT, UPDATE ou
    DELETE — case-insensitive.

    "Começa com" e não "contém" é o que faz `SELECT ... FOR UPDATE` passar
    por leitura (falso negativo ACEITO, ver docstring do módulo) em vez de
    acusar por causa do "UPDATE" no meio da frase. Comentário nunca entra
    aqui de qualquer forma — `ast.parse` descarta comentário; só docstring ou
    literal de verdade poderiam colidir, e nenhum faz isso em
    `src/web/routes` hoje.

    `ast.walk` (não `h.nos_do_corpo_proprio`): quer pegar a marca em
    QUALQUER profundidade léxica dentro do bloco — inclusive dentro de um
    `async with conn.transaction():` aninhado (as 12 rotas da Task 5) —, e
    essa é a direção SEGURA de errar: na pior hipótese, um bloco que na
    verdade só lê fica classificado como "escreve" (não entra na cobrança),
    nunca o contrário.
    """
    for n in ast.walk(no):
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr in ("execute", "executemany")
        ):
            return True
        texto: str | None = None
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            texto = n.value
        elif (
            isinstance(n, ast.JoinedStr)
            and n.values
            and isinstance(n.values[0], ast.Constant)
            and isinstance(n.values[0].value, str)
        ):
            texto = n.values[0].value
        if texto is not None and texto.strip().upper().startswith(_PREFIXOS_DE_ESCRITA):
            return True
    return False


def _e_bloco_acquire(no: ast.AST) -> bool:
    """True se `no` é um `with`/`async with` com algum item chamando
    `.acquire()` — o idioma que este repo usa pra tirar conexão CRUA do pool,
    fora de `run_with_reconnect`. Não amarra ao nome da variável (`pool`):
    mesma resolução por ATRIBUTO que `_cursores_fora_de_transacao` (F58) usa
    pro `.cursor(` — não importa como a variável se chama.

    `pool.acquire() as conn, conn.transaction():` (as 12 rotas da Task 5,
    forma combinada) TAMBÉM casa aqui — o item extra não desqualifica; quem
    isenta essas 12 é `_tem_marca_de_escrita_direta`/`_nomes_que_escrevem`
    encontrando a escrita dentro do bloco, não esta função.
    """
    if not isinstance(no, ast.With | ast.AsyncWith):
        return False
    return any(
        isinstance(item.context_expr, ast.Call)
        and isinstance(item.context_expr.func, ast.Attribute)
        and item.context_expr.func.attr == "acquire"
        for item in no.items
    )


def _e_gerador(escopo: ast.AST) -> bool:
    """True se o corpo PRÓPRIO de `escopo` (sem descer em def/lambda
    aninhado) tem `yield`/`yield from` — função async geradora, incompatível
    com o `Callable[[Connection], Awaitable[T]]` que `run_with_reconnect`
    espera. Ver a seção do docstring do módulo sobre streaming.
    """
    return any(isinstance(n, ast.Yield | ast.YieldFrom) for n in h.nos_do_corpo_proprio(escopo))


def _nomes_que_escrevem(arquivo: Path, *, raiz: Path | None = None) -> set[str]:
    """Nomes de função que `arquivo` chama (um salto, via `src.*`) e cujo
    PRÓPRIO corpo tem marca de escrita direta — ver a seção do docstring do
    módulo sobre o limite de UM salto. `raiz` existe só pro teste de mordida
    montar uma árvore `src.` falsa sob `tmp_path` (mesmo parâmetro que
    `h.funcoes_chamadas_de_src` já expõe pra isso).
    """
    return {
        fn.name
        for _helper_arquivo, fn in h.funcoes_chamadas_de_src(arquivo, raiz=raiz)
        if _tem_marca_de_escrita_direta(fn)
    }


def _ofensores_do_arquivo(arquivo: Path, *, raiz: Path | None = None) -> list[tuple[str, int]]:
    """(nome_da_função_dona, linha) de todo `pool.acquire()` cru, num bloco
    que não escreve nem mora num gerador, em `arquivo` — os sítios que este
    guard cobra.

    `h.funcoes(arv)` inclui função ANINHADA (o `stream()` dos dois exports
    CSV) como escopo PRÓPRIO, separado da função que a define — é por isso
    que `_e_gerador` isenta exatamente o gerador aninhado, não a rota inteira
    que o contém (que nem tem `pool.acquire()` no próprio corpo).
    """
    arv = h.arvore(arquivo)
    nomes_de_escrita = _nomes_que_escrevem(arquivo, raiz=raiz)
    achados: list[tuple[str, int]] = []
    for func in h.funcoes(arv):
        gerador = _e_gerador(func)
        for no in h.nos_do_corpo_proprio(func):
            if not isinstance(no, ast.With | ast.AsyncWith) or not _e_bloco_acquire(no):
                continue
            if gerador:
                continue
            if _tem_marca_de_escrita_direta(no):
                continue
            if any(h.chama(no, nome, arv=arv) for nome in nomes_de_escrita):
                continue
            achados.append((func.name, no.lineno))
    return achados


def _ofensores_do_painel() -> list[str]:
    """`arquivo::função:linha` de todo ofensor sob `src/web/routes/`.

    `h.fontes_py(_ROTAS)` levanta `EscopoVazioError` se o diretório não tiver
    nenhum `.py` — vacuidade aqui não seria "painel limpo", seria scanner
    rodando fora da raiz (o mesmo modo de falha do guard do relógio em
    2026-09-06, catalogado em `_guard_harness.py`).
    """
    achados: list[str] = []
    for arquivo in h.fontes_py(_ROTAS):
        achados.extend(
            f"{h.rel(arquivo)}::{nome}:{linha}" for nome, linha in _ofensores_do_arquivo(arquivo)
        )
    return sorted(achados)


def test_reads_puros_do_painel_usam_run_with_reconnect() -> None:
    """F76/F77/F91 (Task 6, PR 5, 2026-09-17): nenhum bloco que só lê no
    corpo das rotas do painel usa `pool.acquire()` cru.

    Medido ANTES desta task: 36 ofensores (zero `run_with_reconnect` em
    `src/web/routes/`). Depois da conversão dos 19 sítios de leitura pura
    (tabela no relatório da task), o esperado é lista vazia — os 17 que
    ficam de fora (12 rotas transacionais da Task 5, `accounts_revoke_
    connection`, `sessions_create`, o primeiro acquire de `sessions_revoke`,
    e os dois streams de CSV) são exatamente os que `_ofensores_do_arquivo`
    reconhece como escrita, lê-e-escreve ou gerador — não uma lista mantida
    à mão aqui.
    """
    ofensores = _ofensores_do_painel()
    assert not ofensores, (
        "pool.acquire() cru num bloco que só lê, sem run_with_reconnect: "
        f"{ofensores}. asyncpg não faz pre-ping — quando o Supabase fecha o "
        "socket ocioso, o pool inteiro morre, e a PRIMEIRA query depois "
        "disso estoura (F76/F77). Envolva com "
        "`await connection.run_with_reconnect(lambda conn: ...)`."
    )


# --- testes de mordida: o casador, forma a forma -----------------------------


def test_marca_de_escrita_pega_execute_e_executemany() -> None:
    arv = ast.parse("async def f(conn):\n    await conn.execute('SELECT 1')\n")
    assert _tem_marca_de_escrita_direta(arv)
    arv = ast.parse("async def f(conn):\n    await conn.executemany('SELECT 1', [])\n")
    assert _tem_marca_de_escrita_direta(arv)


def test_marca_de_escrita_pega_literal_insert_update_delete_case_insensitive() -> None:
    for verbo in ("INSERT", "update", "Delete"):
        arv = ast.parse(f"async def f(conn):\n    return await conn.fetchval('{verbo} x')\n")
        assert _tem_marca_de_escrita_direta(arv), verbo


def test_marca_de_escrita_nao_acusa_select_for_update() -> None:
    """Falso negativo ACEITO e documentado: 'começa com', não 'contém'."""
    arv = ast.parse(
        "async def f(conn):\n    return await conn.fetchrow('SELECT * FROM t FOR UPDATE')\n"
    )
    assert not _tem_marca_de_escrita_direta(arv)


def test_marca_de_escrita_nao_acusa_leitura_pura() -> None:
    arv = ast.parse(
        "async def f(conn):\n    rows = await conn.fetch('SELECT * FROM t')\n    return rows\n"
    )
    assert not _tem_marca_de_escrita_direta(arv)


def test_marca_de_escrita_pega_update_em_f_string_pelo_prefixo_literal() -> None:
    arv = ast.parse('async def f(conn, n):\n    await conn.execute(f"UPDATE t SET x = {n}")\n')
    assert _tem_marca_de_escrita_direta(arv)


def _unico_with_do_corpo(fonte: str) -> ast.With | ast.AsyncWith:
    """Extrai o único `with`/`async with` do corpo da única função de `fonte`
    — atalho pros testes de mordida de `_e_bloco_acquire`, com narrowing
    explícito (`assert isinstance`) pra mypy strict aceitar o `.body[0]`.
    """
    modulo = ast.parse(fonte)
    func = modulo.body[0]
    assert isinstance(func, ast.AsyncFunctionDef | ast.FunctionDef)
    with_stmt = func.body[0]
    assert isinstance(with_stmt, ast.With | ast.AsyncWith)
    return with_stmt


def test_e_bloco_acquire_reconhece_a_forma_simples_e_a_combinada_com_transacao() -> None:
    simples = _unico_with_do_corpo(
        "async def f():\n    async with pool.acquire() as conn:\n        pass\n"
    )
    assert _e_bloco_acquire(simples)

    combinada = _unico_with_do_corpo(
        "async def f():\n    async with pool.acquire() as conn, conn.transaction():\n        pass\n"
    )
    assert _e_bloco_acquire(combinada)

    outro = _unico_with_do_corpo(
        "async def f():\n    async with conn.transaction():\n        pass\n"
    )
    assert not _e_bloco_acquire(outro)


def test_e_gerador_distingue_funcao_normal_de_streaming() -> None:
    normal = ast.parse("async def f():\n    return 1\n").body[0]
    assert not _e_gerador(normal)

    gerador = ast.parse("async def stream():\n    async for x in y:\n        yield x\n").body[0]
    assert _e_gerador(gerador)


# --- teste de mordida: a resolução de UM salto e o controle positivo do Step 6


def _monta_arvore_fake(tmp_path: Path) -> Path:
    """`tmp_path/rota_fake.py` importando `tmp_path/src/repo_fake.py` — uma
    árvore `src.` mínima e descartável, o mecanismo que `h.funcoes_chamadas_
    de_src` documenta pra teste de mordida sem tocar o repo real.

    `repo_fake.grava` escreve de verdade (UPDATE); `repo_fake.le` só lê. A
    rota fake tem três funções: uma só-leitura (deve acusar), uma que
    DELEGA a escrita pra `grava` sem transação nem palavra de escrita local
    (não deve acusar — é o controle positivo do Step 6: um guard que
    cobrasse `run_with_reconnect` aqui empurraria o repo pro F91), e uma
    geradora que só lê (não deve acusar — exceção de streaming).
    """
    repo_fake = tmp_path / "src" / "repo_fake.py"
    repo_fake.parent.mkdir(parents=True, exist_ok=True)
    repo_fake.write_text(
        "async def grava(conn):\n"
        "    await conn.execute('UPDATE t SET x = 1 WHERE id = $1')\n"
        "\n"
        "async def le(conn):\n"
        "    return await conn.fetchval('SELECT 1')\n",
        encoding="utf-8",
    )
    rota = tmp_path / "rota_fake.py"
    rota.write_text(
        "from src import repo_fake\n"
        "\n"
        "async def so_le():\n"
        "    async with pool.acquire() as conn:\n"
        "        return await repo_fake.le(conn)\n"
        "\n"
        "async def delega_escrita_sem_transacao():\n"
        "    async with pool.acquire() as conn:\n"
        "        await repo_fake.grava(conn)\n"
        "\n"
        "async def stream_de_leitura():\n"
        "    async with pool.acquire() as conn:\n"
        "        async for row in repo_fake.le(conn):\n"
        "            yield row\n",
        encoding="utf-8",
    )
    return rota


def test_resolucao_de_um_salto_acusa_so_a_leitura_pura(tmp_path: Path) -> None:
    """O controle positivo do Step 6, permanente: `delega_escrita_sem_
    transacao` chama `repo_fake.grava` (UPDATE, um salto) sem abrir
    `conn.transaction()` nenhuma — mesmo formato de `accounts_revoke_
    connection` no repo real. Se este teste acusasse essa função, o guard
    estaria cobrando `run_with_reconnect` de uma escrita: o dano que o brief
    da Task 6 chama de PIOR que não converter nada (F91 — retry re-executa a
    escrita). `stream_de_leitura` prova a exceção de geradores no mesmo
    salto; `so_le` prova que o casador ainda acusa o caso comum.
    """
    rota = _monta_arvore_fake(tmp_path)
    achados = dict(_ofensores_do_arquivo(rota, raiz=tmp_path))

    assert achados == {"so_le": 4}, achados
