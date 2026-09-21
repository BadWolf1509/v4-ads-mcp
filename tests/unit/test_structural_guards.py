"""Guards estruturais: varrem o source pra impedir reincidência de classes de bug.

Cada guard aqui existe porque a classe já mordeu em produção e a proteção era
"lembrar de fazer grep manual" (documentada no CLAUDE.md). Um guard automatizado
transforma a convenção num teste que falha no commit em vez de num incidente.

- F57 (Google): call-site de build_client_for_manager sem ensure_account_access
  → vazou existência/schema de qualquer conta da MCC (o validate_gaql ficou
  desguarnecido até a auditoria de 2026-06-20).
- F57-Meta: cliente HTTP (`httpx.AsyncClient`/`Client`/`get`/`post`) construído
  ou invocado fora de quem já gateia → pula o hard-gate (o freio do Modelo B é
  a matriz de acesso; o token é compartilhado). Retargetado DUAS vezes em
  F190/Task 6 (21/09): 1ª pro literal `graph.facebook.com` (ruling R10, quando
  `build_meta_api` sumiu); 2ª pro MECANISMO — cliente HTTP, não URL — depois
  que o fix round 1 provou por mutação que concatenação de string e reuso de
  constante autorizada escapam de qualquer varredura de literal, sempre. A
  invariante nunca mudou: só o executor gateado fala com a Graph API.
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


def _sites_que_buildam(arv: ast.Module) -> list[tuple[ast.AST, str, int]]:
    """(escopo, nome, linha) de cada chamada a `build_client_for_manager`.

    A chamada é atribuída ao escopo MAIS INTERNO que a contém — a mesma
    decisão do `_cursores_fora_de_transacao` (F58), pela mesma razão: quem
    responde pelo call-site é quem o escreve, não quem por acaso o envolve.

    O MÓDULO entra como escopo. Chamada no corpo de módulo (ou de classe) não
    tem função dona e, sem esta linha, escaparia por não ter a quem ser
    atribuída — o mesmo buraco que o F58 fechou incluindo `arv` na lista.

    Separada de `_ofensores_f57` para o teste de `src/` poder CONTAR os
    call-sites vistos: zero call-site não é conta limpa, é scanner quebrado
    (renomearam a factory e o guard passaria vazio).
    """
    achados: list[tuple[ast.AST, str, int]] = []
    for escopo in (arv, *h.funcoes(arv)):
        nome = getattr(escopo, "name", "<módulo>")
        achados.extend(
            (escopo, nome, linha)
            for linha in h.chama_no_corpo_proprio(escopo, "build_client_for_manager", arv=arv)
        )
    return achados


def _tem_gate_f57(escopo: ast.AST, pai: dict[ast.AST, ast.AST | None], arv: ast.Module) -> bool:
    """O hard-gate está no corpo próprio de `escopo` ou no da função que o define.

    **Alcance: o corpo próprio, mais UM nível de subida.** Nem mais nem menos,
    e os dois lados foram medidos.

    *Menos* não dá: o idioma que o F109 obriga é `await run_blocking(_closure)`
    com o SDK dentro do closure, enquanto o gate é I/O async no DB e só pode
    viver na função de fora. Julgar o closure isolado reprovaria o formato que
    outra convenção do projeto exige, e falso positivo ensina a contornar o
    guard.

    *Mais* também não. Até 2026-09-07 a subida era ILIMITADA e o teste do
    ancestral varria a SUBÁRVORE inteira dele — então o gate escrito numa
    closure IRMÃ, num método de classe aninhada, ou dentro de um `if False:`
    isentava a função que builda (medido). Irmã não envolve ninguém: a
    docstring prometia "função que a ENVOLVA" e a implementação conferia
    "qualquer coisa em algum lugar do ancestral". A unidade não tinha deixado
    de ser frouxa — tinha mudado de "arquivo" para "função mais externa".

    Um nível é exatamente o que o F109 exige (o closure é definido DIRETO na
    função gateada; as 6 funções vivas têm um `def` aninhado cada uma). Duas
    camadas de aninhamento entre o gate e o `build` não têm ocupante vivo: se
    aparecer, o remédio é escrever o gate na função que define o closure — não
    alargar o alcance de volta.
    """
    if h.chama_no_corpo_proprio(escopo, "ensure_account_access", arv=arv):
        return True
    mae = pai.get(escopo)
    return mae is not None and bool(h.chama_no_corpo_proprio(mae, "ensure_account_access", arv=arv))


def _ofensores_f57(arv: ast.Module) -> list[tuple[str, int]]:
    """(escopo, linha) de cada `build_client_for_manager` sem gate no fluxo.

    A unidade é a FUNÇÃO. Até 2026-09-07 este guard perguntava do ARQUIVO —
    `"build_client_for_manager(" in text and "ensure_account_access(" not in
    text` — então uma função nova, escrita num arquivo que já gateia NOUTRA
    função, passava verde. A mensagem do próprio guard já mandava "grep TODA
    função que chama": ele enunciava a propriedade e conferia outra. É o mesmo
    defeito de unidade do F58.

    Gate do CHAMADOR não isenta, pela mesma razão registrada no F58: exigiria
    call graph, e o grafo seria incompleto por construção (despacho dinâmico,
    injeção, framework). O alcance do que ISENTA está em `_tem_gate_f57`.
    """
    pai = h.escopos_pais(arv)
    return [
        (nome, linha)
        for escopo, nome, linha in _sites_que_buildam(arv)
        if not _tem_gate_f57(escopo, pai, arv)
    ]


def test_build_client_for_manager_callsites_have_gate() -> None:
    """F57: toda chamada a build_client_for_manager tem o hard-gate no mesmo
    fluxo (no corpo próprio de quem a escreve, ou no da função que a define).

    Sem o gate, o executor fala com QUALQUER conta da MCC: foi assim que o
    `validate_gaql` vazou existência e schema de conta alheia até a auditoria de
    2026-06-20.

    Não há mais allowlist por arquivo. `client.py` era isento inteiro por
    DEFINIR a factory — mas isentar o arquivo é o próprio defeito que este guard
    deixou de ter, e a isenção nunca foi necessária: a definição não chama a si
    mesma (medido em 2026-09-07 — `client.py` tem duas funções e nenhuma delas
    aparece aqui). Com a allowlist fora, um helper novo escrito ao lado da
    factory fica coberto.
    """
    ofensores: list[str] = []
    vistas = 0
    for p in h.fontes_py():
        arv = h.arvore(p)
        vistas += len(_sites_que_buildam(arv))
        ofensores.extend(f"{h.rel(p)}:{linha} (em {nome})" for nome, linha in _ofensores_f57(arv))

    assert vistas, (
        "F57 — o scanner não achou NENHUMA chamada a build_client_for_manager. "
        "Guard que varre zero call-sites passa por vacuidade: ou a factory foi "
        "renomeada (atualize o alvo) ou o casamento quebrou."
    )
    assert not ofensores, (
        "F57 — build_client_for_manager sem ensure_account_access no fluxo: "
        f"{ofensores}. Todo caminho que builda o client Google precisa do hard-gate "
        "no corpo da própria função, ou no corpo da função que a define (um nível "
        "— é o que o formato `run_blocking(_closure)` do F109 exige). Gate em "
        "função IRMÃ não conta: irmã não envolve ninguém."
    )


# (id, fonte, acusa?) — o contrato do guard do F57, forma a forma. As duas
# metades importam igual: `irma_em_arquivo_que_gateia` é o buraco que o guard
# por arquivo deixava passar, e `closure_dentro_de_funcao_gateada` é o formato
# que o F109 obriga e que este guard não pode reprovar.
_FORMAS_F57 = [
    (
        "irma_em_arquivo_que_gateia",
        # O BURACO: função nova num arquivo que já gateia noutra função. Por
        # arquivo passava verde — o `ensure_account_access(` de `gateada`
        # isentava o arquivo inteiro, `nova` inclusive.
        "async def gateada(cid):\n"
        "    await ensure_account_access(cid)\n"
        "    return build_client_for_manager(cid)\n"
        "async def nova(cid):\n"
        "    return build_client_for_manager(cid)\n",
        True,
    ),
    (
        "funcao_unica_com_gate",
        "async def f(cid):\n"
        "    await ensure_account_access(cid)\n"
        "    return build_client_for_manager(cid)\n",
        False,
    ),
    (
        "funcao_unica_sem_gate",
        "async def f(cid):\n    return build_client_for_manager(cid)\n",
        True,
    ),
    (
        "closure_dentro_de_funcao_gateada",
        # Formato exigido pelo F109: o SDK só é tocado dentro do closure passado
        # a `run_blocking`, e o gate é I/O async que não cabe lá. É o único
        # motivo de existir subida nenhuma — e por isso ela para em 1 nível.
        "async def f(cid):\n"
        "    await ensure_account_access(cid)\n"
        "    def _executar():\n"
        "        return build_client_for_manager(cid)\n"
        "    return await run_blocking(_executar)\n",
        False,
    ),
    (
        "closure_dentro_de_funcao_sem_gate",
        "async def f(cid):\n"
        "    def _executar():\n"
        "        return build_client_for_manager(cid)\n"
        "    return await run_blocking(_executar)\n",
        True,
    ),
    (
        "gate_apenas_no_chamador",
        # Mesma decisão do F58: isentar pelo chamador exigiria call graph, e o
        # grafo é incompleto por construção.
        "async def chamador(cid):\n"
        "    await ensure_account_access(cid)\n"
        "    return await executor(cid)\n"
        "async def executor(cid):\n"
        "    return build_client_for_manager(cid)\n",
        True,
    ),
    (
        "alias_de_import_nao_escapa",
        "from src.google_ads.client import build_client_for_manager as _mk\n"
        "async def f(cid):\n    return _mk(cid)\n",
        True,
    ),
    (
        "metodo_de_classe_sem_gate",
        # Método é função: `h.funcoes()` desce em classe, e um executor escrito
        # como método não pode escapar por isso.
        "class Executor:\n"
        "    async def rodar(self, cid):\n"
        "        return build_client_for_manager(cid)\n",
        True,
    ),
    (
        "gate_em_lambda_do_corpo_proprio",
        # O IDIOMA VIVO: 6 dos 6 call-sites do F57 gateiam assim (medido em
        # 2026-09-07). `lambda` é transparente em `nos_do_corpo_proprio`
        # justamente para esta forma não virar falso positivo.
        "async def f(cid):\n"
        "    await run_with_reconnect(lambda conn: ensure_account_access(conn, cid))\n"
        "    return build_client_for_manager(cid)\n",
        False,
    ),
    (
        "gate_em_closure_irma",
        # A SABOTAGEM DO I3: verde até 2026-09-07 porque o teste do ancestral
        # varria a subárvore INTEIRA de `f`, e o gate de `_gate` morava lá.
        # Uma irmã não envolve ninguém — e pode nunca ser chamada.
        "async def f(cid):\n"
        "    async def _gate():\n"
        "        await ensure_account_access(cid)\n"
        "    def _executar():\n"
        "        return build_client_for_manager(cid)\n"
        "    return await run_blocking(_executar)\n",
        True,
    ),
    (
        "gate_em_closure_irma_morta",
        # Pior ainda: a irmã está sob `if False:` e nem existe em runtime.
        "async def f(cid):\n"
        "    if False:\n"
        "        async def _gate():\n"
        "            await ensure_account_access(cid)\n"
        "    return build_client_for_manager(cid)\n",
        True,
    ),
    (
        "gate_em_metodo_de_classe_aninhada",
        # Mesma família: o método é subárvore de `f`, mas não envolve nada.
        "async def f(cid):\n"
        "    class _Aux:\n"
        "        async def gatear(self):\n"
        "            await ensure_account_access(cid)\n"
        "    return build_client_for_manager(cid)\n",
        True,
    ),
    (
        "gate_na_bisavo",
        # Subida limitada a 1 nível: o gate está duas camadas acima do build.
        # Não tem ocupante vivo; o remédio é gatear em `mae`, não realargar.
        "async def bisavo(cid):\n"
        "    await ensure_account_access(cid)\n"
        "    def mae():\n"
        "        def neta():\n"
        "            return build_client_for_manager(cid)\n"
        "        return neta\n"
        "    return mae\n",
        True,
    ),
    (
        "build_no_corpo_do_modulo",
        # Sem função dona: antes de 2026-09-07 o laço só olhava funções, então
        # a chamada no corpo do módulo não era atribuída a ninguém.
        "CLIENT = build_client_for_manager(MANAGER_ID)\n",
        True,
    ),
    (
        "build_em_lambda_sem_gate",
        # `lambda` transparente corta nos dois sentidos: o build escrito dentro
        # de um é atribuído a `f`, em vez de sumir por não ter escopo dono.
        "async def f(cid):\n    return await run_blocking(lambda: build_client_for_manager(cid))\n",
        True,
    ),
]


@pytest.mark.parametrize(
    ("fonte", "acusa"),
    [(fonte, acusa) for _, fonte, acusa in _FORMAS_F57],
    ids=[ident for ident, _, _ in _FORMAS_F57],
)
def test_f57_acusa_a_violacao_e_so_ela(fonte: str, acusa: bool) -> None:
    """Contrato do guard do F57 contra fonte sintética, pela MESMA travessia.

    Sem esta tabela, as duas metades do contrato dependeriam de existir um
    ocupante vivo de cada forma em `src/` — e as seis funções vivas são todas da
    mesma forma (gate na própria função, dentro de um `lambda`). O guard poderia
    ganhar ou perder qualquer uma das outras sem nada ficar vermelho.
    """
    achados = _ofensores_f57(ast.parse(fonte))

    assert bool(achados) is acusa, (
        f"veredito errado: esperado {'ACUSA' if acusa else 'passa'}, "
        f"obtido {achados or 'passa'} para:\n{fonte}"
    )


# F57-Meta RETARGETADO UMA SEGUNDA VEZ (F190/Task 6, 21/09 — fix round 1,
# achado CRITICAL do revisor, provado por mutação com dois probes empíricos
# rodados em `src/`). A 1ª versão (ruling R10) trocou "chamada a
# build_meta_api" por "literal `graph.facebook.com`" quando a função sumiu de
# client.py. Essa versão tinha um defeito de EIXO: o literal é um PROXY de
# quem fala com a Graph API, não o mecanismo. Dois refactors NÃO-adversariais
# — coisa que qualquer um faz sem pensar — escapavam por completo:
#
#   A) concatenação: `"https://graph." + "facebook.com/v22.0"` — nenhum
#      Constant sozinho contém o literal, e `_texto_logico` não junta
#      literais através de um `BinOp`.
#   B) reuso de constante JÁ autorizada: `from src.auth.meta_oauth import
#      META_GRAPH_BASE` num arquivo novo — o literal nunca é REESCRITO, zero
#      ocorrências no arquivo, guard verde.
#
# Os dois probes tinham `httpx.AsyncClient()` no arquivo novo — é isso que
# efetivamente ALCANÇA a Graph API, não importa como a URL foi montada depois.
# Uma tool não pode fazer requisição sem construir (ou receber já construído)
# um cliente; o literal é opcional, o cliente não é.
#
# Retargetado pro MECANISMO: o guard varre as raízes abaixo procurando
# CONSTRUÇÃO/USO DIRETO de cliente HTTP (`_METODOS_CLIENTE_HTTP`) e afirma que
# só acontece em (arquivo, escopo) autorizados. Resolução por CAMINHO
# CANÔNICO (`h.origens_de_import` + `h.caminho_canonico`), não pelo último
# nome do atributo — `import httpx as hx` ou `from httpx import AsyncClient`
# resolvem pro mesmo alvo que `import httpx; httpx.AsyncClient(...)`.
#
# FIX ROUND 2 (achado do revisor, mesma sessão): o conjunto só cobria
# `httpx`/`requests` — a frase de abertura de `test_meta_graph_execution_is_contained`
# ("só o executor gateado pode construir OU USAR cliente HTTP") era mais larga
# do que isso verificava. O revisor mediu os escapes reais e ordenou por
# plausibilidade; dois viraram cobertura, o resto virou limite DECLARADO (ver
# a docstring do teste — despacho dinâmico não é perseguido aqui):
#
#   - `aiohttp.ClientSession()` — plausibilidade ALTA: `aiohttp` já é
#     dependência instalada (`pyproject.toml`, pin de segurança
#     PYSEC-2026-3545/3546/3547, transitiva via `facebook-business`) — quem
#     escrever `import aiohttp` não instala nada novo nem sente que está
#     fazendo algo diferente.
#   - `urllib.request.urlopen(...)` — stdlib, custo zero, reflexo comum de
#     quick fix.
_METODOS_CLIENTE_HTTP = frozenset(
    {
        "httpx.AsyncClient",
        "httpx.Client",
        "httpx.get",
        "httpx.post",
        "httpx.put",
        "httpx.delete",
        "httpx.patch",
        "httpx.request",
        "httpx.stream",
        # Defensivo: `requests` não tem consumidor real em src/meta_ads/ nem
        # src/auth/ desde a Task 3 (medido — o `requests` que resta em
        # reports.py é prosa, não import). Se algo reverter parcial pro SDK
        # antigo (que usa `requests` por baixo via facebook_business), a
        # chamada direta equivalente já está coberta.
        "requests.get",
        "requests.post",
        "requests.put",
        "requests.delete",
        "requests.patch",
        "requests.request",
        "requests.Session",
        # Fix round 2: aiohttp cobre construtor (ClientSession) E o helper de
        # um-tiro (aiohttp.request), no mesmo padrão de completude do httpx
        # acima — deixar só ClientSession coberto reproduziria, dentro do
        # aiohttp, a MESMA assimetria que este round inteiro existe pra
        # fechar (biblioteca X tem verbo coberto, biblioteca Y não).
        "aiohttp.ClientSession",
        "aiohttp.request",
        # urllib.request.Request() sozinho não é I/O (só monta o objeto,
        # como httpx.Headers()) — urlopen() é quem manda a requisição, com
        # ou sem Request por trás. Cobrir só o verbo que FAZ I/O é a mesma
        # precisão do caso "httpx_helper_nao_relacionado_nao_conta" abaixo.
        "urllib.request.urlopen",
    }
)

# Piso de arquivos de tool Meta sob src/mcp/tools/ — protege a DESCOBERTA de
# arquivo (eixo diferente do piso de ocorrência abaixo): se a convenção de
# nome mudar (deixar de conter "meta"), `_raizes_cliente_http_meta` erraria
# calado varrendo uma fração da superfície. Medido: `ls src/mcp/tools/ | grep
# -i meta` = 8 arquivos, 2026-09-21.
_PISO_ARQUIVOS_TOOLS_META = 8


def _raizes_cliente_http_meta() -> list[Path]:
    """Arquivos varridos pelo guard: todo `src/meta_ads/**.py` (recursivo, já
    com o `EscopoVazioError` de `h.fontes_py` embutido) + os handlers de tool
    Meta em `src/mcp/tools/` (nome contém "meta", direto no diretório — tools
    não vivem em subpasta).

    Escopo deliberadamente MENOR que `src/` inteiro: `httpx` é usado em áreas
    do repo sem nenhuma relação com a Graph API (`src/auth/oauth.py` é o
    OAuth do GOOGLE, por exemplo) — varrer ali geraria ruído sem proteger
    nada, e é exatamente o "restrinja às raízes" que o revisor pediu.

    FICAM DE FORA, apesar de construírem `httpx.AsyncClient` de verdade e
    falarem com a Graph API — cada um por motivo medido, não por esquecimento:

    - `src/auth/meta_oauth.py` (2 construções reais: `meta_oauth_callback` e
      `meta_oauth_refresh_accounts`) — o roteador OAuth inteiro. Não é onde
      uma TOOL nova nasce; é arquivo estável, tocado só quando o fluxo OAuth
      muda. Era allowlist no guard anterior (literal, por módulo inteiro);
      aqui fica de FORA do escopo por decisão, não por buraco herdado.
    - `src/jobs/meta_resync.py` (1 construção real) — o job de resync roda
      com o token de system-user direto, automação privilegiada sem
      manager_id no caminho. Mesma classe de "anterior ao gate por natureza".

    Isto é uma FRONTEIRA CONHECIDA, não uma garantia universal: uma tool ou
    job Meta que alguém escreva FORA destas duas raízes (outro diretório do
    repo, uma rota nova em `src/web/routes/`) NÃO é coberto por este guard —
    nada aqui afirma o contrário.
    """
    raiz_meta_ads = h.fontes_py(h.SRC / "meta_ads")
    tools_meta = sorted(
        p.resolve() for p in (h.SRC / "mcp" / "tools").glob("*.py") if "meta" in p.stem.lower()
    )
    if len(tools_meta) < _PISO_ARQUIVOS_TOOLS_META:
        raise h.EscopoVazioError(
            f"só {len(tools_meta)} arquivo(s) de tool Meta encontrado(s) sob "
            f"src/mcp/tools/ (piso: {_PISO_ARQUIVOS_TOOLS_META}, medido em "
            "2026-09-21). A convenção de nome pode ter mudado (deixou de "
            "conter 'meta') — o guard estaria varrendo só uma fração da "
            "superfície de tools, calado."
        )
    return raiz_meta_ads + tools_meta


# A allowlist é a invariante deste guard, não uma exceção temporária — pequena,
# fechada, revisada, e cada entrada carrega o motivo AO LADO (entrada sem
# motivo é entrada que ninguém reavalia depois).
_ALLOWLIST_CLIENTE_HTTP: dict[tuple[str, str], str] = {
    ("src/meta_ads/reports.py", "run_meta_graph_get"): (
        "o executor único: can_manager_access roda incondicional ANTES do "
        "`async with httpx.AsyncClient(...)` (linha 160, contra a 234) — o "
        "freio do Modelo B. Nenhuma outra função deste arquivo constrói "
        "cliente (medido: só _paginar_graph mais existe, e RECEBE `http` por "
        "parâmetro — usa o cliente que o executor já gateou, não constrói um "
        "novo)."
    ),
}

# Medido em 2026-09-21 (fix round 1): sob as duas raízes de
# `_raizes_cliente_http_meta`, exatamente 1 construção real de cliente —
# `httpx.AsyncClient(...)` em `reports.py:234`. Nenhum dos 8 arquivos de tool
# constrói cliente (todos delegam a `run_meta_graph_get`); `graph.py` e
# `partnership.py` RECEBEM `http` por parâmetro, não constroem.
#
# HONESTO SOBRE A REDUNDÂNCIA (achado Minor do revisor): com allowlist de 1
# entrada só, este piso e a checagem por-entrada (`vistos_por_entrada`)
# afirmam a MESMA coisa hoje — a checagem por-entrada já implica que o total
# não pode ser zero enquanto a entrada existir. Não finjo que são
# independentes. Mantenho os dois porque (a) o valor é MEDIDO, não decoração,
# e (b) no dia em que a allowlist ganhar uma 2ª entrada, ou em que uma
# revisão quiser saber "o total caiu?" sem percorrer cada chave, o piso deixa
# de ser redundante sem precisar de desenho novo. Se isto continuar do mesmo
# jeito na próxima rodada, considere apagar um dos dois em vez de manter os
# dois por hábito.
_PISO_CLIENTE_HTTP = 1


def _ocorrencias_cliente_http(arv: ast.Module, caminho_rel: str) -> list[tuple[str, int, bool]]:
    """(escopo, linha, autorizado) de cada Call que constrói/invoca um cliente
    HTTP (`_METODOS_CLIENTE_HTTP`) no corpo PRÓPRIO de cada escopo.

    Resolve o alvo pelo CAMINHO CANÔNICO (`h.origens_de_import` +
    `h.caminho_canonico`), não pelo último nome do atributo: `httpx.get(`
    bate por `Attribute`, `from httpx import AsyncClient` + `AsyncClient(`
    bate por `Name` resolvido via import, e `import httpx as hx` +
    `hx.AsyncClient(` bate pelos dois — as três formas usam a MESMA
    resolução, então renomear o import não escapa (mesma lição do F57
    original, aplicada ao módulo em vez do nome de uma função).

    Um cliente RECEBIDO por parâmetro (`http.get(...)`, onde `http` é
    argumento, não import) nunca resolve pra `httpx.*` — `caminho_canonico`
    só reconhece raiz ligada por `import`/`from import` no PRÓPRIO arquivo.
    É por isso que `graph.py::fetch_paginated` e
    `partnership.py::fetch_partnership` (que recebem `http: httpx.AsyncClient`
    de fora) não aparecem aqui: USAM um cliente que já passou pelo construtor
    gateado, não CONSTROEM um novo.
    """
    origens = h.origens_de_import(arv)
    achados: list[tuple[str, int, bool]] = []
    for escopo in (arv, *h.funcoes(arv)):
        nome = getattr(escopo, "name", "<módulo>")
        for no in h.nos_do_corpo_proprio(escopo):
            if not isinstance(no, ast.Call):
                continue
            caminho = h.caminho_canonico(no.func, origens)
            if caminho not in _METODOS_CLIENTE_HTTP:
                continue
            achados.append((nome, no.lineno, (caminho_rel, nome) in _ALLOWLIST_CLIENTE_HTTP))
    return achados


def _ofensores_f57_meta(arv: ast.Module, caminho_rel: str) -> list[tuple[str, int]]:
    """(escopo, linha) de cada construção/uso de cliente HTTP fora da allowlist."""
    return [
        (nome, linha)
        for nome, linha, autorizado in _ocorrencias_cliente_http(arv, caminho_rel)
        if not autorizado
    ]


def test_meta_graph_execution_is_contained() -> None:
    """F57-Meta: só o executor gateado pode CONSTRUIR ou usar diretamente um
    cliente HTTP (`httpx`/`aiohttp`/`urllib.request` — ver
    `_METODOS_CLIENTE_HTTP` pro conjunto exato) contra a Graph API. Uma tool
    nova que construa o próprio cliente pula `can_manager_access` — o único
    freio do Modelo B (token compartilhado entre ~24 contas) — não importa
    COMO ela monte a URL depois.

    **O que este guard NÃO pega — limite estrutural, não descuido, e a
    mesma classe de limite que `h.chama()` já documenta pra despacho
    dinâmico.** A varredura é sintática (AST); ela resolve `Name`,
    `Attribute` e alias de import (`caminho_canonico`), mas não executa nada.
    Três formas ficam de fora POR CONSTRUÇÃO, confirmadas rodando contra este
    scanner (fix round 2, 2026-09-21 — nenhuma das três produz achado):

    - `getattr(httpx, "AsyncClient")()` — o alvo da chamada é o RETORNO de um
      `getattr`, não um `Name`/`Attribute` estático.
    - `importlib.import_module("httpx").AsyncClient()` — a base do atributo
      é uma `Call`, não uma raiz que `origens_de_import` conhece.
    - `__import__("httpx").AsyncClient()` — mesma forma do caso acima.

    Resolver estas três exigiria executar o código (ou modelar `getattr`/
    `importlib` especificamente), e um scanner que tentasse cobrir despacho
    dinâmico goela abaixo ficaria gordo e cheio de falso positivo — o mesmo
    trade-off que `chama()` já aceita e documenta. **Este guard pega o
    caminho HONESTO — o refactor que ninguém pensaria duas vezes antes de
    escrever — não o adversarial.** Quem precisar de garantia contra código
    deliberadamente ofuscado precisa de outra camada, não deste guard.

    Retargetado DUAS vezes em F190/Task 6 (21/09). Fix round 1 (achado
    Critical do revisor, provado por mutação com dois probes empíricos): a 1ª
    versão (ruling R10) varria o LITERAL `graph.facebook.com` — um PROXY de
    quem fala com a API, não o mecanismo. Concatenação de string e reuso de
    uma constante já autorizada escapavam por completo (ver o comentário
    acima de `_METODOS_CLIENTE_HTTP` pros dois probes). Os dois tinham
    `httpx.AsyncClient()` no arquivo novo — é isso que este guard vigia desde
    então. Fix round 2 (achado do revisor, mesma sessão): o conjunto só
    cobria `httpx`/`requests`, deixando `aiohttp` (dependência já instalada)
    e `urllib.request.urlopen` (stdlib) de fora sem que o docstring avisasse
    — ver o comentário de `_METODOS_CLIENTE_HTTP` pros dois novos. Ver
    `_raizes_cliente_http_meta` pro escopo de ARQUIVO (e o que fica de fora,
    deliberadamente) e `_ALLOWLIST_CLIENTE_HTTP` pra allowlist com o motivo
    de cada entrada.
    """
    vistos_por_entrada: dict[tuple[str, str], int] = {chave: 0 for chave in _ALLOWLIST_CLIENTE_HTTP}
    total_vistas = 0
    ofensores: list[str] = []
    for p in _raizes_cliente_http_meta():
        caminho_rel = h.rel(p)
        for nome, linha, autorizado in _ocorrencias_cliente_http(h.arvore(p), caminho_rel):
            total_vistas += 1
            chave = (caminho_rel, nome)
            if autorizado:
                vistos_por_entrada[chave] += 1
            else:
                ofensores.append(f"{caminho_rel}:{linha} (em {nome})")

    assert total_vistas >= _PISO_CLIENTE_HTTP, (
        f"F57-Meta — só {total_vistas} construção(ões)/uso(s) de cliente HTTP sob as "
        f"raízes varridas, piso {_PISO_CLIENTE_HTTP} (medido em 2026-09-21). Varredura "
        "achando MENOS do que já viu antes passa por vacuidade: ou `_METODOS_CLIENTE_HTTP` "
        "parou de casar (o import mudou de forma que `caminho_canonico` não resolve) ou o "
        "único site conhecido sumiu sem atualizar este piso na mesma mudança."
    )
    faltando = sorted(chave for chave, n in vistos_por_entrada.items() if n == 0)
    assert not faltando, (
        f"F57-Meta — entrada(s) da allowlist sem NENHUMA construção/uso real: {faltando}. "
        "A allowlist é a invariante deste guard: entrada que não casa nada é entrada que "
        "ninguém reavalia — confirme se o site migrou e remova a entrada, ou se é vacuidade "
        "de scanner."
    )
    assert not ofensores, (
        f"F57-Meta — cliente HTTP construído/usado fora dos lugares autorizados: "
        f"{ofensores}. Toda leitura Meta deve passar por run_meta_graph_get "
        "(can_manager_access incondicional — o único freio do Modelo B), não importa como "
        "a URL foi montada. Se o site novo é legítimo, acrescente (arquivo, escopo) a "
        "`_ALLOWLIST_CLIENTE_HTTP` COM o motivo ao lado."
    )


# (id, caminho_rel sintético, fonte, acusa?) — contrato do guard F57-Meta
# (mecanismo), forma a forma, pela MESMA travessia que o teste de `src/` usa.
# "concatenacao_de_url_ainda_e_pega" e "constante_importada_ainda_e_pega" são
# os DOIS PROBES do achado Critical do fix round 1; "aiohttp_client_session_e_pego",
# "aiohttp_request_e_pego" e "urllib_urlopen_e_pego" são os do fix round 2 —
# sem eles aqui, uma regressão futura do MECANISMO ou do CONJUNTO
# (`_METODOS_CLIENTE_HTTP` perde uma entrada num refactor) só apareceria
# rodando o probe manual de novo, nunca num `pytest` de rotina.
_FORMAS_F57_META = [
    (
        "no_proprio_executor",
        "src/meta_ads/reports.py",
        "async def run_meta_graph_get(edge):\n"
        "    async with httpx.AsyncClient() as http:\n"
        "        return await http.get(edge)\n",
        False,
    ),
    (
        "funcao_nova_no_arquivo_do_executor",
        # A MESMA sabotagem de sempre, agora sobre o cliente: função nova em
        # reports.py que TAMBÉM constrói httpx.AsyncClient, sem passar pelo
        # gate de run_meta_graph_get.
        "src/meta_ads/reports.py",
        "async def run_meta_graph_get(edge):\n"
        "    async with httpx.AsyncClient() as http:\n"
        "        return await http.get(edge)\n"
        "async def zz_atalho(edge):\n"
        "    async with httpx.AsyncClient() as http:\n"
        "        return await http.get(edge)\n",
        True,
    ),
    (
        "arquivo_nao_autorizado",
        "src/meta_ads/_qualquer_novo.py",
        "async def ler():\n"
        "    async with httpx.AsyncClient() as http:\n"
        '        return await http.get("https://graph.facebook.com/v22.0/me")\n',
        True,
    ),
    (
        "concatenacao_de_url_ainda_e_pega",
        # PROBE A do revisor: a varredura por LITERAL não pegava isto —
        # nenhum Constant sozinho contém "graph.facebook.com". A varredura
        # por MECANISMO nem olha a URL.
        "src/meta_ads/_qualquer_novo.py",
        "async def ler(edge):\n"
        '    host = "https://graph." + "facebook.com/v22.0"\n'
        "    async with httpx.AsyncClient() as http:\n"
        "        return await http.get(host + edge)\n",
        True,
    ),
    (
        "constante_importada_ainda_e_pega",
        # PROBE B do revisor: zero ocorrências do literal neste arquivo (a
        # constante é importada, não reescrita) — a varredura por LITERAL
        # ficava verde. A varredura por MECANISMO não precisa do literal.
        "src/meta_ads/_qualquer_novo.py",
        "from src.auth.meta_oauth import META_GRAPH_BASE\n"
        "async def ler(edge):\n"
        "    async with httpx.AsyncClient() as http:\n"
        "        return await http.get(META_GRAPH_BASE + edge)\n",
        True,
    ),
    (
        "aiohttp_client_session_e_pego",
        # PROBE do fix round 2: aiohttp já é dependência instalada (pin de
        # segurança transitivo via facebook-business) — ninguém precisa
        # instalar nada pra chegar aqui.
        "src/meta_ads/_qualquer_novo.py",
        "import aiohttp\n"
        "async def ler(url):\n"
        "    async with aiohttp.ClientSession() as sessao:\n"
        "        return await sessao.get(url)\n",
        True,
    ),
    (
        "aiohttp_request_e_pego",
        # O helper de um-tiro do aiohttp — mesmo papel do httpx.get/post.
        "src/meta_ads/_qualquer_novo.py",
        "import aiohttp\n"
        "async def ler(url):\n"
        '    async with aiohttp.request("GET", url) as resp:\n'
        "        return resp\n",
        True,
    ),
    (
        "urllib_urlopen_e_pego",
        # PROBE do fix round 2: stdlib, custo zero — o outro escape que o
        # revisor classificou como plausível.
        "src/meta_ads/_qualquer_novo.py",
        "import urllib.request\ndef ler(url):\n    return urllib.request.urlopen(url)\n",
        True,
    ),
    (
        "cliente_recebido_por_parametro_nao_conta",
        # A forma real de graph.py::fetch_paginated: RECEBE `http`, não
        # CONSTRÓI. `caminho_canonico` só resolve raiz ligada por import no
        # PRÓPRIO arquivo — parâmetro nunca aparece em `origens_de_import`.
        "src/meta_ads/_qualquer_novo.py",
        "async def usa_cliente_alheio(http, edge):\n    return await http.get(edge)\n",
        False,
    ),
    (
        "httpx_helper_nao_relacionado_nao_conta",
        # Precisão do conjunto: httpx.Headers()/httpx.URL() não enviam
        # requisição nem constroem cliente — não estão em
        # _METODOS_CLIENTE_HTTP. reports.py usa httpx.Headers() de verdade
        # (linha 80, dentro de _paginar_graph) e não pode acender o guard.
        "src/meta_ads/_qualquer_novo.py",
        "def monta_headers():\n    return httpx.Headers()\n",
        False,
    ),
    (
        "alias_de_import_nao_escapa",
        "src/meta_ads/_qualquer_novo.py",
        "import httpx as hx\n"
        "async def ler(edge):\n"
        "    async with hx.AsyncClient() as http:\n"
        "        return await http.get(edge)\n",
        True,
    ),
    (
        "from_import_bare_form_e_pego",
        "src/meta_ads/_qualquer_novo.py",
        "from httpx import AsyncClient\n"
        "async def ler(edge):\n"
        "    async with AsyncClient() as http:\n"
        "        return await http.get(edge)\n",
        True,
    ),
]


@pytest.mark.parametrize(
    ("caminho_rel", "fonte", "acusa"),
    [(caminho, fonte, acusa) for _, caminho, fonte, acusa in _FORMAS_F57_META],
    ids=[ident for ident, _, _, _ in _FORMAS_F57_META],
)
def test_f57_meta_acusa_a_violacao_e_so_ela(caminho_rel: str, fonte: str, acusa: bool) -> None:
    """Contrato do guard F57-Meta (mecanismo), forma a forma, pela MESMA
    travessia que o teste de `src/` usa (`_ofensores_f57_meta`).
    """
    achados = _ofensores_f57_meta(ast.parse(fonte), caminho_rel)

    assert bool(achados) is acusa, (
        f"veredito errado: esperado {'ACUSA' if acusa else 'passa'}, "
        f"obtido {achados or 'passa'} para {caminho_rel}:\n{fonte}"
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


# Metodos de `DockerContainer` (testcontainers) que, JUNTOS, dao os dois
# ingredientes pra montar um DSN a mao sem passar por
# `PostgresContainer.get_connection_url()` — e portanto sem passar pela
# correcao de IPv4 do `_dsn`. Confirmado por introspecao da classe instalada
# (2026-09-11, `PostgresContainer.__mro__`): as duas moram na base
# `DockerContainer`, nao em `PostgresContainer` — por isso chamar SO uma delas
# e comum (ex.: afirmar que a porta foi publicada) e nao significa montagem de
# DSN; so o PAR conta.
_METODOS_DSN_A_MAO = frozenset({"get_container_host_ip", "get_exposed_port"})


def _ofensores_dsn_a_mao(arv: ast.Module) -> list[tuple[int, str]]:
    """(linha, motivo) de cada jeito de montar DSN sem passar pela fixture `_dsn`.

    Duas formas, as duas por AST — nunca substring de linha crua:

    1. Chamada a `get_connection_url`, em QUALQUER forma (`Name`, `Attribute`
       ou alias de import — mesma resolucao de `h.nomes_locais`, que os outros
       guards deste arquivo usam pra F57/F58). E o metodo que `_dsn` embrulha
       pra forcar 127.0.0.1 no win32.
    2. Host E porta obtidos direto do container (`get_container_host_ip` +
       `get_exposed_port` — ver `_METODOS_DSN_A_MAO`). Os dois JUNTOS sao os
       unicos ingredientes que essa API oferece pra montar uma URL de conexao
       sem nunca escrever o nome `get_connection_url` — o "outro caminho" da
       mesma familia do F81 que a docstring do teste ja cita. Exigir o PAR
       evita acusar um teste que so confirme que a porta foi publicada, sem
       compor DSN nenhum.

    Limite conhecido, documentado em vez de perseguido: um `get_exposed_port`
    de um lado do arquivo e um `get_container_host_ip` do outro, sem relacao
    entre si, ainda acusam — a unidade aqui e o ARQUIVO, nao a funcao nem o
    f-string que de fato junta os dois. Mais estreito exigiria rastrear se as
    duas chamadas alimentam a mesma string, e nenhum ocupante (vivo ou de
    sabotagem) precisa dessa precisao: hoje NENHUM teste de integracao chama
    qualquer um dos dois metodos (grep 2026-09-11), entao o falso positivo e
    hipotetico, nao medido.
    """
    nomes_gcu = h.nomes_locais(arv, "get_connection_url")
    achados: list[tuple[int, str]] = []
    linha_por_metodo: dict[str, int] = {}
    for no in ast.walk(arv):
        if not isinstance(no, ast.Call):
            continue
        f = no.func
        if (isinstance(f, ast.Name) and f.id in nomes_gcu) or (
            isinstance(f, ast.Attribute) and f.attr in nomes_gcu
        ):
            achados.append((no.lineno, "get_connection_url"))
        elif isinstance(f, ast.Attribute) and f.attr in _METODOS_DSN_A_MAO:
            linha_por_metodo.setdefault(f.attr, no.lineno)
    if linha_por_metodo.keys() >= _METODOS_DSN_A_MAO:
        achados.append((max(linha_por_metodo.values()), "host+porta do container formatados a mao"))
    return achados


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

    **Aperto (rodada 1, Task 7 — tabela 3.1.1 #5 da spec de 2026-09-06).** O
    escopo ja era recursivo (`h.testes_py(integracao)`, resolvido de graca pela
    conversao pro harness no PR0) — o que faltava era o CASADOR: substring de
    `"get_connection_url(" in linha`, linha a linha. Verdadeiro so pra essa
    grafia exata; cego a `get_connection_url` chamado via alias de import; e
    cego por construcao a quem nunca escreve o nome `get_connection_url` — quem
    monta o DSN pegando host e porta direto do container
    (`get_container_host_ip`/`get_exposed_port`) e formatando a URL a mao passa
    reto. `_ofensores_dsn_a_mao` resolve por AST (Name/Attribute/alias, igual
    aos outros guards deste arquivo) e cobre as duas formas.
    """
    integracao = Path(__file__).resolve().parents[1] / "integration"
    conftest = integracao / "conftest.py"
    offenders = []
    for p in h.testes_py(integracao):
        if p == conftest:
            continue
        for numero, motivo in _ofensores_dsn_a_mao(h.arvore(p)):
            offenders.append(f"{p.name}:{numero} ({motivo})")
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


def _audit_admin_esta_na_transacao(escopo: ast.AST, arv: ast.Module) -> bool:
    """True se o corpo PRÓPRIO de `escopo` (sem descer em def/lambda aninhados,
    ver `h.nos_do_corpo_proprio`) tem um `with`/`async with` de `.transaction()`
    cujo PRÓPRIO NÓ — não o corpo inteiro da função — contém uma chamada a
    `_audit_admin`.

    Revisão da branch (item A): a versão anterior desta função (chamada
    `_abre_transacao_no_corpo_proprio`) só perguntava "a função abre uma
    transação em algum lugar do próprio corpo?" — presença bastava. Isso
    responde o adjacente, não a invariante da Task 5: um `_audit_admin`
    desindentado para DEPOIS do `async with conn.transaction():` deixa a
    função "abrindo uma transação em algum lugar" (a pergunta antiga continua
    True) mas quebra a atomicidade que o teste existe pra proteger. Provado
    por AST sintético na revisão: `BOM` (audit dentro) e `QUEBRADO` (audit
    desindentado pra fora) davam os DOIS `True` na versão antiga.

    Acha o nó `AsyncWith`/`With` do `.transaction()` (mesma resolução de nome
    de `h.chama`, casando `Attribute.attr` com alias via `h.nomes_locais` —
    não importa se a variável de conexão se chama `conn`, `connection` ou
    outra coisa) e roda `h.chama` NELE — que faz `ast.walk` do NÓ da
    transação, não do corpo inteiro da função — perguntando por `_audit_admin`
    dentro. Se houver mais de um bloco de transação no corpo, basta um conter
    o audit.
    """
    nomes_transaction = h.nomes_locais(arv, "transaction")
    for no in h.nos_do_corpo_proprio(escopo):
        if not isinstance(no, ast.AsyncWith | ast.With):
            continue
        eh_transacao = any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Attribute)
            and item.context_expr.func.attr in nomes_transaction
            for item in no.items
        )
        if eh_transacao and h.chama(no, "_audit_admin", arv=arv):
            return True
    return False


# As 12 rotas da Task 5 (2026-09-17): mudança de acesso (ou de gestor, ou de
# convite) e a linha de audit_log que a documenta gravadas como uma escrita
# só. Path -> nomes é a forma que o brief autoriza enumerar — o conjunto é
# conhecido e fechado, e só chegou a 12 depois de duas medições erradas (uma
# casava por palavra-chave e perdia `admin_managers_toggle_active`, cujo corpo
# diz `is_active`, não `access`; a outra exigia chamada de repositório e
# perdia as duas de SQL cru). O que o guard não aceita calado é um desses 12
# nomes sumir do código — ver a asserção de `faltando` no teste abaixo.
_ROTAS_ACESSO_E_AUDIT_ATOMICOS: dict[Path, frozenset[str]] = {
    h.SRC / "web" / "routes" / "admin_access.py": frozenset(
        {
            "admin_access_meta_toggle",
            "admin_access_meta_bulk_grant",
            "admin_access_meta_bulk_copy",
            "admin_access_bulk_grant",
            "admin_access_bulk_copy",
            "admin_access_toggle",
        }
    ),
    h.SRC / "web" / "routes" / "admin_accounts.py": frozenset(
        {"admin_accounts_google_restore", "admin_accounts_meta_restore"}
    ),
    h.SRC / "web" / "routes" / "admin_overview.py": frozenset(
        {"admin_managers_toggle_active", "admin_managers_toggle_role"}
    ),
    h.SRC / "web" / "routes" / "admin_invites.py": frozenset(
        {"admin_invites_new", "admin_invites_cancel"}
    ),
}


def test_acesso_e_audit_abrem_a_mesma_transacao_nas_12_rotas() -> None:
    """Task 5 (2026-09-17): as 12 rotas admin que mudam acesso (ou gestor, ou
    convite) e gravam `audit_log` fazem as duas escritas como UMA transação.

    Sem isso, audit falhando depois da escrita já commitada deixa o estado
    mudado sem registro de quem mudou — numa ferramenta cuja governança
    inteira se apoia no `audit_log`, o pior desfecho possível (pior que a
    mudança falhar: falha visível alguém conserta). O comportamento de
    transação/rollback é provado com Postgres real em
    `tests/integration/test_acesso_e_audit_sao_atomicos.py` (3 das 12, uma por
    forma de escrita); este guard prova a INVARIANTE ESTRUTURAL nas 12, não só
    nas 3 exercitadas ali — sem ele, nada impede as outras 9 de reincidir.

    `faltando` dispara ANTES de perguntar sobre transação: uma rota renomeada
    ou movida pra outro módulo tem que acusar por sumir da lista, não sair
    silenciosamente da cobertura — é o modo de falha nº1 catalogado neste repo
    (CLAUDE.md, "Don't fechar sprint..."; findings-catalog.md).

    Revisão da branch (item A): o casador é `_audit_admin_esta_na_transacao`,
    não só "abre uma transação em algum lugar" — ver o docstring dela pra
    prova de que a versão antiga não discriminava `_audit_admin` DENTRO de
    FORA do bloco.
    """
    faltando: list[str] = []
    audit_fora_da_transacao: list[str] = []

    for caminho, nomes in _ROTAS_ACESSO_E_AUDIT_ATOMICOS.items():
        arv = h.arvore(caminho)
        achadas = {
            no.name: no
            for no in arv.body
            if isinstance(no, ast.AsyncFunctionDef | ast.FunctionDef) and no.name in nomes
        }
        for nome in sorted(nomes):
            func = achadas.get(nome)
            if func is None:
                faltando.append(f"{h.rel(caminho)}::{nome}")
                continue
            if not _audit_admin_esta_na_transacao(func, arv):
                audit_fora_da_transacao.append(f"{h.rel(caminho)}::{nome}")

    assert not faltando, (
        f"rota da Task 5 sumiu do código: {faltando}. Rename ou move tira a "
        "cobertura deste guard em silêncio — enumerar os 12 nomes só vale "
        "enquanto o guard acusa quando um deles some."
    )
    assert not audit_fora_da_transacao, (
        "rota muda acesso mas `_audit_admin` não está DENTRO do "
        f"`async with conn.transaction():` que protege a escrita: {audit_fora_da_transacao}. "
        "Se a função abre a transação e audita depois de sair dela (ou não audita "
        "nesse bloco nenhum), a segunda escrita (audit) falhando depois da primeira "
        "já commitada deixa o acesso mudado sem registro de quem mudou."
    )
