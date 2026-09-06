"""Guards estruturais: varrem o source pra impedir reincidência de classes de bug.

Cada guard aqui existe porque a classe já mordeu em produção e a proteção era
"lembrar de fazer grep manual" (documentada no CLAUDE.md). Um guard automatizado
transforma a convenção num teste que falha no commit em vez de num incidente.

- F57 (Google): call-site de build_client_for_manager sem ensure_account_access
  → vazou existência/schema de qualquer conta da MCC (o validate_gaql ficou
  desguarnecido até a auditoria de 2026-06-20).
- F57-Meta: chamada à Graph API fora de run_meta_graph_get → pula o hard-gate
  (o freio do Modelo B é a matriz de acesso; o token é compartilhado).
- F58: conn.cursor() sem async with conn.transaction() → asyncpg exige transação
  pra server-side cursor (o CSV export quebrou em prod porque nenhum teste iterou).
- F83: I/O de bookkeeping num `finally` sem best_effort → exceção ali DESCARTA o
  `return` pendente do `try`, virando erro numa mutação já aplicada no provider
  (e apagando a própria linha de audit que deveria registrá-la).
"""

import ast
from pathlib import Path

import pytest

from tests.unit import _guard_harness as h

SRC = h.SRC  # mantido: guards usam `p.relative_to(SRC)` na mensagem


def test_build_client_for_manager_callsites_have_gate() -> None:
    """F57: todo arquivo que CHAMA build_client_for_manager também chama
    ensure_account_access. client.py o DEFINE (allowlist)."""
    definer = SRC / "google_ads" / "client.py"
    offenders = []
    for p in h.fontes_py():
        if p == definer:
            continue
        text = p.read_text(encoding="utf-8")
        if "build_client_for_manager(" in text and "ensure_account_access(" not in text:
            offenders.append(str(p.relative_to(SRC)))
    assert not offenders, (
        "F57 — call-site de build_client_for_manager SEM ensure_account_access: "
        f"{offenders}. Todo caminho que builda o client Google precisa do hard-gate "
        "no mesmo fluxo (grep TODA função que chama build_client_for_manager)."
    )


def test_meta_graph_execution_is_contained() -> None:
    """F57-Meta: build_meta_api (o factory de execução com o system-user token) só
    pode ser chamado dentro de run_meta_graph_get (reports.py), que aplica o gate.
    client.py o DEFINE. Um tool que chame direto pularia o hard-gate incondicional."""
    allowed = {
        SRC / "meta_ads" / "client.py",  # define build_meta_api
        SRC / "meta_ads" / "reports.py",  # run_meta_graph_get — único executor
    }
    offenders = []
    for p in h.fontes_py():
        if p in allowed:
            continue
        if "build_meta_api(" in p.read_text(encoding="utf-8"):
            offenders.append(str(p.relative_to(SRC)))
    assert not offenders, (
        "F57-Meta — build_meta_api chamado fora de reports.py: "
        f"{offenders}. Toda leitura Meta deve passar por run_meta_graph_get "
        "(gate can_manager_access + audit + BUC)."
    )


def _cursores_fora_de_transacao(escopo: ast.AST, arv: ast.Module) -> list[int]:
    """Linhas de `.cursor(` no corpo PRÓPRIO de `escopo`, fora de transação.

    Não desce em função aninhada: cada função é um escopo próprio e é visitada
    em separado por `h.funcoes()`. Atribuir a chamada ao escopo MAIS INTERNO é
    o que impede que uma transação escrita na função de fora isente um closure
    que pode ser chamado de qualquer outro lugar.

    `desce` testa o nó que RECEBE e só então desce nos filhos, e trata o `with`
    que RECEBE — não o `with` que encontra entre os filhos. As duas coisas são a
    mesma lição, aprendida em duas rodadas:

    1. Enquanto o teste do `.cursor(` vivia no laço dos filhos, um `.cursor(`
       que É o `context_expr` de um `with` (`async with conn.cursor('q') as c:`)
       nunca era testado — ele chega a `desce` como o próprio `no`, nunca como
       filho de alguém. O guard por ARQUIVO pegava essa forma por substring e a
       conversão para AST a perdeu (medido e fechado em 2026-09-06).
    2. Enquanto o tratamento do `with` vivia no laço dos filhos, um `with`
       ANINHADO — que chega a `desce` como `no`, pela recursão da linha do corpo
       — tinha os `items` ignorados, e a transação declarada nele não protegia
       nada. Isso acusava o idioma padrão do asyncpg (`async with
       pool.acquire() as conn:` por fora, `async with conn.transaction():` por
       dentro), que é CÓDIGO CORRETO. Falso positivo é pior que guard ausente:
       ensina a contornar o guard. Achado na revisão final, 2026-09-06.

    A transação vale para todo o corpo léxico do `with`, aninhamento adentro —
    mas só dentro da MESMA função: `desce` não entra em `def`/`async def`/
    `lambda`, cada um é escopo próprio visitado em separado. Transação aberta
    pelo CHAMADOR continua não isentando (ver a docstring do teste).
    """
    nus: list[int] = []

    def desce(no: ast.AST, protegido: bool) -> None:
        if (
            not protegido
            and isinstance(no, ast.Call)
            and isinstance(no.func, ast.Attribute)
            and no.func.attr in h.nomes_locais(arv, "cursor")
        ):
            nus.append(no.lineno)
        if isinstance(no, ast.With | ast.AsyncWith):
            # Os itens são avaliados em ordem, então o que vem DEPOIS de
            # `conn.transaction()` no mesmo `async with` já está dentro dela
            # (`async with pool.acquire() as conn, conn.transaction():`).
            aqui = protegido
            for item in no.items:
                desce(item.context_expr, aqui)
                if item.optional_vars is not None:
                    desce(item.optional_vars, aqui)  # `as d[algo()]` é sintaxe válida
                if h.chama(item.context_expr, "transaction", arv=arv):
                    aqui = True
            for stmt in no.body:
                desce(stmt, aqui)
            return  # items + body são TODOS os filhos de um With; nada sobra
        for filho in ast.iter_child_nodes(no):
            if isinstance(filho, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
                continue  # escopo próprio — `h.funcoes()`/`h.lambdas()` o visitam sozinhos
            desce(filho, protegido)

    desce(escopo, False)
    return nus


def _ofensores_f58(arv: ast.Module) -> list[tuple[str, int]]:
    """(escopo, linha) de cada `.cursor(` fora de transação num módulo.

    Fonte única do laço de escopos: o teste que varre `src/` e o que exercita as
    quatro formas sintéticas chamam esta mesma função. Duas travessias com a
    mesma intenção seriam duas fontes de verdade — o F91 ao pé da letra.
    """
    achados: list[tuple[str, int]] = []
    # O módulo entra como escopo: `.cursor(` fora de qualquer função (corpo de
    # módulo ou de classe) não pode escapar por não ter função dona. O `lambda`
    # entra pelo mesmo motivo que a função aninhada — é escopo próprio, `desce`
    # o pula no laço de filhos, e sem ele aqui o corpo não seria visitado por
    # NINGUÉM (I1 da revisão final: `g = lambda: conn.cursor('q')` passava).
    for escopo in (arv, *h.funcoes(arv), *h.lambdas(arv)):
        if not h.chama(escopo, "cursor", arv=arv):
            continue
        onde = "<lambda>" if isinstance(escopo, ast.Lambda) else getattr(escopo, "name", "<módulo>")
        achados.extend((onde, linha) for linha in _cursores_fora_de_transacao(escopo, arv))
    return achados


def test_cursor_usage_is_wrapped_in_transaction() -> None:
    """F58: `.cursor(` só roda dentro de `async with conn.transaction()`.

    asyncpg exige transação explícita pro server-side cursor; sem ela o
    generator quebra com `NoActiveSQLTransactionError` no primeiro fetch — foi
    assim que o CSV export foi pra produção quebrado.

    A versão anterior era `".cursor(" in text and "conn.transaction()" not in
    text`, por ARQUIVO e por substring. Medido em 2026-09-06, ela deixava
    passar duas coisas:

    1. **Unidade errada.** Um segundo generator com `conn.cursor(` sem
       transação, num arquivo que já abre transação NOUTRA função, passava
       verde — uma transação em qualquer lugar do arquivo isentava o arquivo
       inteiro. É o mesmo defeito de unidade do F57, e é por isso que
       `h.funcoes()` existe.
    2. **Prosa contando como código.** `conn.transaction()` escrito em
       comentário ou docstring satisfazia o `not in text`. Não é hipótese:
       cinco arquivos citam a chamada em COMENTÁRIO (`conversions.py:107`,
       `customer_match.py:165`, `mutations.py:201`, `reports.py:87`,
       `validate_gaql.py:125`); num arquivo onde só o comentário existisse, o
       guard ficava verde sem nenhuma transação real — sabotagem F58-C.

    **Decisão sobre transação aberta pelo CHAMADOR (2026-09-06): não isenta.**
    A transação tem que estar na própria função, envolvendo lexicalmente a
    chamada. Três razões. (a) Confiar no chamador é exatamente o que produziu o
    F58: o generator é lazy, e num streaming CSV quem o consome é o iterador de
    resposta do Starlette, fora de qualquer transação que a rota tenha aberto —
    o `async with` do chamador só protege se ele consumir o generator inteiro
    lá dentro, o que nenhum guard estático verifica. (b) Isentar pelo chamador
    exigiria call graph, e o grafo seria inevitavelmente incompleto (despacho
    dinâmico, injeção, consumo dirigido por framework) — uma isenção que não
    distingue código bom de quebrado não é guard. (c) O remédio é barato e já é
    o idioma da casa: transação aninhada no asyncpg vira SAVEPOINT (ver o
    comentário em `validate_gaql.py:125`), então declarar a transação dentro da
    própria função nunca custa correção.
    """
    ofensores: list[str] = []
    for path in h.fontes_py():
        for onde, linha in _ofensores_f58(h.arvore(path)):
            ofensores.append(f"{h.rel(path)}:{linha} (em {onde})")

    assert not ofensores, (
        f"F58 — `.cursor(` fora de `async with conn.transaction()`: {ofensores}. "
        "asyncpg exige transação explícita pro server-side cursor, senão o "
        "generator quebra com NoActiveSQLTransactionError no primeiro fetch. A "
        "transação precisa estar na PRÓPRIA função, envolvendo a chamada — "
        "transação aberta pelo chamador NÃO conta (o generator é lazy e pode ser "
        "consumido fora dela), e aninhar vira SAVEPOINT, que é barato."
    )


# Cada entrada é (id, fonte, acusa?). A tabela é o contrato do guard do F58:
# quais formas ele PRECISA acusar e quais ele NÃO PODE acusar. As duas metades
# importam igual — um guard que reprova código correto é pior que um guard
# ausente, porque ensina a contorná-lo (revisão final, 2026-09-06).
_FORMAS_F58 = [
    (
        "aninhado_acquire_fora_transacao_dentro",
        # Idioma padrão do asyncpg, e o que o único `.cursor(` vivo do projeto
        # usa em espírito. Acusar isto era o falso positivo do I2.
        "async def f(pool):\n"
        "    async with pool.acquire() as conn:\n"
        "        async with conn.transaction():\n"
        "            async for r in conn.cursor('q'):\n"
        "                pass\n",
        False,
    ),
    (
        "clausula_unica_acquire_e_transacao",
        "async def f(pool):\n"
        "    async with pool.acquire() as conn, conn.transaction():\n"
        "        async for r in conn.cursor('q'):\n"
        "            pass\n",
        False,
    ),
    (
        "cursor_nu",
        "async def f(conn):\n    c = conn.cursor('q')\n    return c\n",
        True,
    ),
    (
        "cursor_dentro_de_lambda",
        # Lambda é escopo próprio e o corpo dele só roda depois — a forma mais
        # curta de produzir o consumo preguiçoso que o F58 existe pra impedir.
        "async def f(conn):\n    g = lambda: conn.cursor('q')\n    return g\n",
        True,
    ),
    (
        "lambda_dentro_de_transacao_tambem_acusa",
        # Deliberado, não descuido: o lambda pode ser chamado depois que o
        # `async with` fechou. É a mesma razão pela qual transação do CHAMADOR
        # não isenta.
        "async def f(conn):\n"
        "    async with conn.transaction():\n"
        "        g = lambda: conn.cursor('q')\n"
        "    return g\n",
        True,
    ),
    (
        "cursor_como_context_expr_sem_transacao",
        "async def f(conn):\n    async with conn.cursor('q') as c:\n        pass\n",
        True,
    ),
    (
        "cursor_como_context_expr_protegido_na_mesma_clausula",
        "async def f(conn):\n"
        "    async with conn.transaction(), conn.cursor('q') as c:\n"
        "        pass\n",
        False,
    ),
    (
        "cursor_depois_de_a_transacao_fechar",
        "async def f(conn):\n"
        "    async with conn.transaction():\n"
        "        pass\n"
        "    c = conn.cursor('q')\n"
        "    return c\n",
        True,
    ),
    (
        "transacao_apenas_no_chamador",
        # Decisão registrada em 2026-09-06 e NÃO desfeita pelo fix do `with`
        # ancestral: só o aninhamento léxico DENTRO da mesma função isenta.
        "async def chamador(conn):\n"
        "    async with conn.transaction():\n"
        "        async for r in stream(conn):\n"
        "            pass\n"
        "async def stream(conn):\n"
        "    async for r in conn.cursor('q'):\n"
        "        yield r\n",
        True,
    ),
]


@pytest.mark.parametrize(
    ("fonte", "acusa"),
    [(fonte, acusa) for _, fonte, acusa in _FORMAS_F58],
    ids=[ident for ident, _, _ in _FORMAS_F58],
)
def test_f58_acusa_a_violacao_e_so_ela(fonte: str, acusa: bool) -> None:
    """Contrato do guard do F58, forma a forma, contra fonte sintética.

    Roda contra `_ofensores_f58` — a MESMA travessia que o teste de `src/` usa,
    não uma reimplementação. Sem esta tabela, as duas metades do contrato
    dependiam de haver um ocupante vivo de cada forma em `src/`, e hoje há
    exatamente um `.cursor(` no projeto inteiro: o guard poderia ganhar ou
    perder qualquer uma das outras oito sem nada ficar vermelho.
    """
    achados = _ofensores_f58(ast.parse(fonte))

    assert bool(achados) is acusa, (
        f"veredito errado: esperado {'ACUSA' if acusa else 'passa'}, "
        f"obtido {achados or 'passa'} para:\n{fonte}"
    )


def _funcoes_que_pegam_conexao_propria() -> set[str]:
    """Nomes de funções em src/ que abrem conexão por conta própria."""
    nomes: set[str] = set()
    for p in h.fontes_py():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
                continue
            # O idioma no codebase é `pool = get_pool()` + `pool.acquire()`, então
            # o `.acquire` NÃO pende de `get_pool()` no AST — casar os dois na
            # mesma função é o que identifica quem abre conexão sozinha.
            if h.chama(node, "get_pool", arv=tree) and h.chama(node, "acquire", arv=tree):
                nomes.add(node.name)
    return nomes


def test_nao_chama_helper_que_pega_conexao_dentro_de_acquire() -> None:
    """F92: chamar helper auto-adquirente DENTRO de um acquire é deadlock latente.

    O chamador segura uma conexão e espera por outra. Com o pool esgotado, quem
    espera nunca é servido — e `pool.acquire()` do asyncpg **não tem timeout por
    default**, então a espera é para sempre, não um erro.

    Era o caso de 4 rotas admin que chamavam `pending_invites_count()` dentro do
    `async with pool.acquire()`, enquanto as outras 7 chamavam fora — a
    inconsistência mostrava que não era intencional.
    """
    auto_adquirentes = _funcoes_que_pegam_conexao_propria()
    offenders = []
    for p in h.fontes_py():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncWith):
                continue
            # É um `async with ...acquire()...`?
            if not any(h.chama(item.context_expr, "acquire", arv=tree) for item in node.items):
                continue
            for corpo in node.body:
                for sub in ast.walk(corpo):
                    if not isinstance(sub, ast.Call):
                        continue
                    alvo = sub.func
                    nome = (
                        alvo.id
                        if isinstance(alvo, ast.Name)
                        else alvo.attr
                        if isinstance(alvo, ast.Attribute)
                        else None
                    )
                    if nome and nome in auto_adquirentes:
                        offenders.append(f"{p.relative_to(SRC)}:{sub.lineno} ({nome})")
    assert not offenders, (
        f"F92 — helper que abre a própria conexão chamado DENTRO de um acquire: {offenders}. "
        "Segurar uma conexão e esperar por outra trava para sempre com o pool cheio "
        "(asyncpg não tem timeout de acquire por default). Mova a chamada pra fora do "
        "`async with`."
    )


def test_gaql_nao_usa_doubling_de_aspas() -> None:
    """F87: GAQL escapa string literal com BARRA INVERTIDA, não com doubling de SQL.

    Verificado empiricamente contra a API real: `IN ('O''Brien')` retorna
    `invalid value 'Brien'`, enquanto `IN ('O\\'Brien')` valida. O padrão `''`
    veio de reflexo de SQL e quebrava nomes legítimos (`Lead - D'Or`).

    O guard é AST, não grep de texto. A primeira versão casava a linha crua e o
    ÚNICO infrator que ela achou foi a docstring de `_gaql.py`, que cita o padrão
    antigo justamente pra explicar por que ele é errado — a armadilha registrada
    na nota de método de 2026-08-11: a prosa que descreve a regra dispara o guard
    que a aplica. Casando a CHAMADA no AST, comentário e docstring ficam
    invisíveis por construção.
    """
    offenders = []
    for p in h.fontes_py():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover — src sempre parseia
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or len(node.args) != 2:
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "replace"):
                continue
            a, b = node.args
            if (
                isinstance(a, ast.Constant)
                and isinstance(b, ast.Constant)
                and a.value == "'"
                and b.value == "''"
            ):
                offenders.append(f"{p.relative_to(SRC)}:{node.lineno}")
    assert not offenders, (
        f"F87 — doubling de aspas ('') pra escapar GAQL: {offenders}. "
        "GAQL não é SQL nisso: use gaql_string_literal/gaql_escape de "
        "src/google_ads/queries/_gaql.py (barra invertida, e a barra vem primeiro)."
    )


def test_finally_bookkeeping_is_best_effort() -> None:
    """F83: I/O de bookkeeping (audit/quota) dentro de `finally` precisa estar sob
    best_effort.

    Exceção levantada num `finally` DESCARTA o `return` pendente do `try`. Como os
    executores adquirem conexão ali pra gravar audit e reconciliar quota, uma
    conexão asyncpg stale (F76) fazia uma mutação JÁ APLICADA no Google voltar como
    erro — o gestor via falha, o cliente LLM tendia a re-tentar operação
    não-idempotente, e a linha de audit não era gravada.

    O guard é por BLOCO (não por arquivo): cada statement do `finally` que adquire
    conexão tem que estar sob best_effort no mesmo statement.
    """
    offenders = []
    for p in h.fontes_py():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover — src sempre parseia
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try) or not node.finalbody:
                continue
            for stmt in node.finalbody:
                if h.chama(stmt, "acquire", arv=tree) and not h.chama(
                    stmt, "best_effort", arv=tree
                ):
                    offenders.append(f"{p.relative_to(SRC)}:{stmt.lineno}")
    assert not offenders, (
        "F83 — pool.acquire() em `finally` sem best_effort: "
        f"{offenders}. Bookkeeping OBSERVA a operação, não decide o resultado dela: "
        "envolva com `async with best_effort(...)` (src/governance/bookkeeping.py), "
        "senão a falha do audit derruba a mutação já aplicada."
    )


def test_teste_de_integracao_nao_monta_dsn_do_container_a_mao() -> None:
    """DSN montado fora do `_dsn` do conftest perde a correcao de host do Windows.

    O Docker Desktop publica a porta em `[::]` e `localhost` resolve pra ::1 E
    127.0.0.1. O listener IPv6 ACEITA o TCP mas nao entrega o payload ao
    container, entao o asyncpg conecta, manda o startup packet e espera pra
    sempre — TimeoutError. `_dsn` forca 127.0.0.1 no win32; quem chama
    `get_connection_url()` direto contorna a correcao e falha SO no Windows,
    que e o pior tipo de quebra (o CI fica verde e o dev local nao roda nada).

    Aconteceu de verdade: depois de consertar o `_dsn`, os 2 testes de
    `test_migrations.py` seguiram falhando porque montavam o DSN inline. Use a
    fixture `pg_dsn`. E a mesma classe do F81 — dois caminhos pro mesmo dado,
    um deles errado e silencioso.
    """
    integracao = Path(__file__).resolve().parents[1] / "integration"
    conftest = integracao / "conftest.py"
    offenders = []
    for p in h.testes_py(integracao):
        if p == conftest:
            continue
        texto = p.read_text(encoding="utf-8")
        for numero, linha in enumerate(texto.splitlines(), start=1):
            if "get_connection_url(" in linha:
                offenders.append(f"{p.name}:{numero}")
    assert not offenders, (
        "teste de integracao montando DSN do container a mao: "
        f"{offenders}. Use a fixture `pg_dsn` (tests/integration/conftest.py) — "
        "ela aplica a correcao de IPv4 que o Docker no Windows exige."
    )


# ----------------------------------------------------------------- F86 (loop)

# Métodos que fazem I/O de rede BLOQUEANTE e portanto não podem ser chamados de
# dentro de um `async def` sem sair do event loop.
#   - google-ads: cliente gRPC síncrono.
#   - facebook_business: `FacebookAdsApi.call` usa `requests` (verificado na
#     fonte instalada — não é coroutine).
# `*_path()`, `get_type()` e `copy_from()` do SDK Google são locais: ficam fora.
_METODOS_BLOQUEANTES = frozenset(
    {
        "search",
        "search_stream",
        "mutate",
        "upload_click_conversions",
        "upload_call_conversions",
        "create_offline_user_data_job",
        "add_offline_user_data_job_operations",
        "run_offline_user_data_job",
        "apply_recommendation",
        "dismiss_recommendation",
        "list_accessible_customers",
    }
)

# `accounts.py` é síncrono DE PROPÓSITO: só o Cloud Run Job de resync o importa
# (verificado), e ali bloquear não tira o loop de ninguém. Ver _blocking.py.
_ARQUIVOS_FORA_DO_LOOP = frozenset({"src/jobs/account_resync.py"})


def _chamadas_diretas(node: ast.AST) -> list[tuple[int, str, str, str]]:
    """Chamadas no corpo de `node`, SEM descer em funções aninhadas.

    Pular as funções aninhadas é o ponto: elas são exatamente os closures que
    `run_blocking` recebe. O que sobra roda no event loop.
    """
    achadas: list[tuple[int, str, str, str]] = []
    pilha: list[ast.AST] = list(ast.iter_child_nodes(node))
    while pilha:
        atual = pilha.pop()
        if isinstance(atual, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if isinstance(atual, ast.Call):
            if isinstance(atual.func, ast.Attribute):
                # `api.call(...)` do facebook_business: o receptor importa, senao
                # o guard casaria qualquer metodo chamado `call` no codebase.
                receptor = atual.func.value
                nome_receptor = receptor.id if isinstance(receptor, ast.Name) else ""
                achadas.append((atual.lineno, atual.func.attr, "attr", nome_receptor))
            elif isinstance(atual.func, ast.Name):
                achadas.append((atual.lineno, atual.func.id, "name", ""))
        pilha.extend(ast.iter_child_nodes(atual))
    return achadas


def _funcoes_sync_bloqueantes() -> dict[str, str]:
    """Funções sync de src/ que bloqueiam, direta ou transitivamente.

    O fecho transitivo importa: `run_recommendation_action` não chamava o SDK,
    chamava `execute_apply_recommendation`, que chama. Um guard que só olhasse
    nomes de método do SDK daria verde nele.
    """
    corpos: dict[str, tuple[str, set[str]]] = {}
    for p in h.fontes_py():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                chamados = {nome for _, nome, _forma, _r in _chamadas_diretas(node)}
                corpos[node.name] = (p.as_posix(), chamados)

    bloqueantes = {
        nome: arq for nome, (arq, chamados) in corpos.items() if chamados & _METODOS_BLOQUEANTES
    }
    mudou = True
    while mudou:
        mudou = False
        for nome, (arq, chamados) in corpos.items():
            if nome not in bloqueantes and (chamados & set(bloqueantes)):
                bloqueantes[nome] = arq
                mudou = True
    return bloqueantes


def test_chamada_bloqueante_sai_do_event_loop() -> None:
    """F86: SDK síncrono chamado de `async def` congela a INSTÂNCIA inteira.

    O google-ads é gRPC bloqueante e o facebook_business usa `requests`. Com
    `--concurrency=80` uma dessas chamadas serializa todos os requests da
    instância — inclusive o `/health?deep=1`, cujo `asyncio.timeout(5)` nem
    começa a contar, porque o timer só dispara quando o loop volta a girar.

    O guard exige que a chamada (e o consumo do resultado) esteja dentro de uma
    função aninhada — o closure que `run_blocking` offloada.

    Nasceu depois de o F86 ser fechado SEM guard nenhum: três sites que servem
    request ficaram para trás (`validate_gaql`, `run_recommendation_action` e o
    executor Meta inteiro), e nada no CI notou.
    """
    bloqueantes = _funcoes_sync_bloqueantes()
    ofensores: list[str] = []
    for p in h.fontes_py():
        rel = p.relative_to(SRC.parent).as_posix()
        if rel in _ARQUIVOS_FORA_DO_LOOP:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            for linha, nome, forma, receptor in _chamadas_diretas(node):
                # Metodo do SDK: SEMPRE chamada de atributo (`ga_service.search`).
                # Exigir a forma evita o falso positivo de uma FUNCAO async nossa
                # com o mesmo nome do metodo — `run_offline_user_data_job` e as
                # duas coisas, e o guard acusava o executor async que ja offloada.
                sdk = forma == "attr" and nome in _METODOS_BLOQUEANTES
                meta = forma == "attr" and nome == "call" and receptor == "api"
                helper = forma == "name" and nome in bloqueantes
                if sdk or meta or helper:
                    ofensores.append(f"{rel}:{linha} async {node.name}() -> {nome}()")

    assert not ofensores, (
        "chamada bloqueante rodando no event loop — envolva num closure e passe "
        "pra run_blocking (F86): " + "; ".join(sorted(ofensores))
    )


def _tabela_de_imports(arv: ast.Module) -> dict[str, str]:
    """Nome local → caminho canônico, lido dos `import` do módulo.

    `h.classe_de_excecao` resolve o nome LITERAL contra `builtins`/`asyncpg`, e
    por isso devolve `None` pra qualquer alias — `except PCE` e
    `except pg.ConnectionDoesNotExistError` passavam verdes mesmo com o
    `issubclass` no lugar (medido 2026-09-06). Desfazer o alias ANTES de
    resolver é o que fecha o buraco; sem isto, renomear no import desarma o
    guard inteiro.

    Import relativo fica de fora de propósito: não dá caminho absoluto pra
    resolver, e nenhuma exceção retentável entra por ele.
    """
    tabela: dict[str, str] = {}
    for no in ast.walk(arv):
        if isinstance(no, ast.Import):
            for a in no.names:
                tabela[a.asname or a.name] = a.name
        elif isinstance(no, ast.ImportFrom):
            if no.module is None or no.level:
                continue
            for a in no.names:
                tabela[a.asname or a.name] = f"{no.module}.{a.name}"
    return tabela


def _canonizar(nome: str, tabela: dict[str, str]) -> str:
    """Troca o primeiro segmento do nome pelo caminho por onde ele foi importado."""
    cabeca, ponto, resto = nome.partition(".")
    destino = tabela.get(cabeca)
    if destino is None:
        return nome
    return f"{destino}{ponto}{resto}" if ponto else destino


def test_retentaveis_de_conexao_tem_uma_fonte_de_verdade_so() -> None:
    """F91 (4ª vez) — quem captura exceção de conexão IMPORTA a constante.

    `run_with_reconnect` retenta o que estiver em `_DROPPED_CONNECTION_ERRORS`.
    Um `except` que repete essa tupla como literal cria duas fontes de verdade
    do mesmo dado: no dia em que a constante ganhar um membro, o `except` fica
    para trás EM SILÊNCIO — a exceção nova escapa, o retry re-executa o closure
    inteiro e o F91 reabre sem nenhum teste ficar vermelho.

    A versão anterior comparava NOME (`{e.__name__ for e in ...}`) contra o
    texto do `except`, e por isso só pegava a grafia que ninguém escreve.
    Medido em 2026-09-06, 5 das 6 grafias ofensoras passavam verdes:

        PEGA   except asyncpg.PostgresConnectionError
        PASSA  except asyncpg.ConnectionDoesNotExistError   <- connection.py:21
        PASSA  except ConnectionResetError                  <- connection.py:22
        PASSA  except (asyncpg.ConnectionFailureError, BrokenPipeError)
        PASSA  except PCE                       <- from asyncpg import X as PCE
        PASSA  except pg.ConnectionDoesNotExistError   <- import asyncpg as pg

    As cinco que passavam são `issubclass` de verdade dos membros da
    constante — logo `run_with_reconnect` as retenta, que é a condição exata do
    F91 — e são justamente as que o comentário de `connection.py:21-22` nomeia
    como as reais. A propriedade só se afirma resolvendo a classe e perguntando
    `issubclass`; comparar string afirma o ADJACENTE à invariante.

    Trocar nome por `issubclass` sozinho ainda deixava as DUAS formas de alias
    passarem (`except PCE` e `except pg.ConnectionDoesNotExistError`), porque
    `h.classe_de_excecao` resolve o nome literal e alias nenhum existe em
    `builtins`/`asyncpg` — medido 2026-09-06, com o `issubclass` já no lugar.
    Por isso o nome passa antes por `_canonizar`: sem isso, um `as` no import
    desarmava o guard inteiro.

    Guard estrutural de propósito: as duas formas são hoje semanticamente
    idênticas, então nenhum teste de comportamento distingue uma da outra. O
    que distingue é se a lista está escrita duas vezes.

    Limite conhecido e deliberado: `h.classe_de_excecao` só resolve `builtins`
    e `asyncpg` (a allowlist existe pra que o texto de um `except` lido de
    fonte arbitrária não decida qual módulo este processo importa), então uma
    subclasse de retentável DEFINIDA no próprio `src/` devolveria `None` e
    passaria. Verificado em 2026-09-06: nenhuma classe de `src/` herda de
    `ConnectionError` nem de exceção do asyncpg. `None` conta como isento aqui
    — e não como ofensor — porque o conjunto retentável está inteiro dentro dos
    dois namespaces cobertos; tratar desconhecido como ofensor acusaria todo
    `except` de exceção própria do projeto.

    Segundo limite conhecido, e o que mais importa estar escrito: nome ligado
    por ATRIBUIÇÃO escapa. `RETRY = (asyncpg.ConnectionDoesNotExistError,
    ConnectionResetError)` seguido de `except RETRY:` fica VERDE, porque
    `_canonizar` lê só a tabela de `import` — `RETRY` não resolve estaticamente
    para nenhuma classe, `h.classe_de_excecao` devolve `None`, e o desconhecido
    conta como isento (mesma escolha do parágrafo acima). Isto é o F91 ao pé da
    letra: a tupla copiada, duas fontes de verdade do mesmo dado — a forma que
    o guard existe para impedir é justamente a que ele não vê. Não é regressão
    (o guard antigo também passava) e não há ocupante vivo, mas fechá-la
    exigiria rastrear atribuição, e fica registrado aqui para que a próxima
    leitura não tome a asserção por completa e a afrouxe achando que sobra.
    """
    from src.db import connection

    definidor = h.SRC / "db" / "connection.py"  # quem DEFINE a constante
    retentaveis = connection._DROPPED_CONNECTION_ERRORS
    ofensores: list[str] = []

    for path in h.fontes_py():
        if path == definidor:
            continue
        arv = h.arvore(path)
        tabela = _tabela_de_imports(arv)
        for no in ast.walk(arv):
            if not isinstance(no, ast.ExceptHandler):
                continue
            for nome in h.excecoes_do_handler(no):
                canonico = _canonizar(nome, tabela)
                if canonico.endswith("_DROPPED_CONNECTION_ERRORS"):
                    continue  # importou a constante: é exatamente o que se quer
                classe = h.classe_de_excecao(canonico)
                if classe is not None and issubclass(classe, retentaveis):
                    ofensores.append(f"{h.rel(path)}:{no.lineno} ({nome})")

    assert not ofensores, (
        "except capturando exceção que `run_with_reconnect` RETENTA, sem importar "
        f"`_DROPPED_CONNECTION_ERRORS`: {ofensores}. Duas fontes de verdade do "
        "mesmo dado divergem — e a divergência aqui reabre o F91 sem teste vermelho."
    )
