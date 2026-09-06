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


def test_cursor_usage_is_wrapped_in_transaction() -> None:
    """F58: arquivo que usa conn.cursor() (server-side cursor) precisa também
    de conn.transaction() — asyncpg exige transação explícita, senão o generator
    quebra no primeiro fetch (o CSV export foi pra prod quebrado assim)."""
    offenders = []
    for p in h.fontes_py():
        text = p.read_text(encoding="utf-8")
        if ".cursor(" in text and "conn.transaction()" not in text:
            offenders.append(str(p.relative_to(SRC)))
    assert not offenders, (
        "F58 — .cursor() sem conn.transaction() no mesmo arquivo: "
        f"{offenders}. async for row in conn.cursor(...) PRECISA de "
        "async with conn.transaction()."
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


def test_retentaveis_de_conexao_tem_uma_fonte_de_verdade_so() -> None:
    """F91 (3ª vez) — quem captura exceção de conexão IMPORTA a constante.

    `run_with_reconnect` retenta o que estiver em `_DROPPED_CONNECTION_ERRORS`.
    Um `except` que repete essa tupla como literal cria duas fontes de verdade
    do mesmo dado: no dia em que a constante ganhar um membro, o `except` fica
    para trás EM SILÊNCIO — a exceção nova escapa, o retry re-executa o closure
    inteiro e o F91 reabre sem nenhum teste ficar vermelho.

    Guard estrutural de propósito: as duas formas são hoje semanticamente
    idênticas, então nenhum teste de comportamento distingue uma da outra. O
    que distingue é se a lista está escrita duas vezes.
    """
    from src.db import connection

    nomes_retentaveis = {e.__name__ for e in connection._DROPPED_CONNECTION_ERRORS}
    ofensores: list[str] = []

    for path in h.fontes_py():
        if path.name == "connection.py":  # quem DEFINE a constante (allowlist)
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            for handler in node.handlers:
                if handler.type is None:
                    continue
                capturadas = (
                    handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
                )
                # Nome de exceção mencionado literalmente, sem passar pela constante.
                mencionados = {
                    e.attr if isinstance(e, ast.Attribute) else e.id
                    for e in capturadas
                    if isinstance(e, ast.Attribute | ast.Name)
                }
                if mencionados & nomes_retentaveis:
                    ofensores.append(f"{path.relative_to(SRC.parent)}:{handler.lineno}")

    assert not ofensores, (
        "except repetindo as exceções retentáveis como literal em vez de importar "
        f"`_DROPPED_CONNECTION_ERRORS`: {ofensores}. Duas fontes de verdade do mesmo "
        "dado divergem — e a divergência aqui reabre o F91 sem teste vermelho."
    )
