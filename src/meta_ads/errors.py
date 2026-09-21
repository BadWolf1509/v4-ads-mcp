"""Map Meta Graph API errors → PT-BR friendly errors for V4 gestores."""

import re
from dataclasses import dataclass

# Familia de throttle do Graph. Cada um e um limite DIFERENTE, e todos passam:
#   4     — limite da aplicacao (app-level rate limit)
#   17    — limite do usuario (user-level rate limit)
#   613   — limite de chamadas do endpoint ("calls to this api have exceeded")
#   80004 — limite especifico de ads management
# Ate a PR 6 so o 4 (e o subcode 2635) eram reconhecidos; os outros tres caiam
# no ramo generico com retryable=False, e um throttle de minutos chegava ao
# gestor como falha permanente.
CODIGOS_DE_THROTTLE = frozenset({4, 17, 613, 80004})

# Subcodes de token invalidado server-side ANTES do expiry natural — o Meta faz
# isso, e o gestor precisa reconectar pelo painel em vez de esperar.
SUBCODES_DE_CONEXAO_EXPIRADA = frozenset({458, 467, 460, 463})

# F190 — qualquer coisa que pareca credencial numa query string sai ANTES de a
# mensagem chegar a um sink. Cobre `access_token`, `appsecret_proof` e
# `client_secret`; os dois primeiros eram injetados sem opt-out pelo SDK
# (`FacebookSession.__init__`) no transporte antigo, e o terceiro aparece no
# fluxo OAuth.
#
# Denylist e reconhecidamente fraca — por isso ela e a SEGUNDA linha de defesa.
# A primeira e o transporte nao por o token na URL (Task 3). Esta existe porque
# uma camada so e a que falha, e este finding e a prova: a invariante do F82
# estava escrita e mesmo assim o vazamento ficou aberto num dos dois caminhos.
#
# Round 1 do F190 (revisao) mediu que a primeira versao deste regex — so
# `nome=valor` sem aspas coladas — deixava passar TRES formas reais:
# `access_token="X"` (aspa colada no `=`), `{"access_token": "X"}` (JSON,
# separador `:`, aspas duplas) e `{'client_secret': 'X'}` (JSON/repr Python,
# aspas simples). O separador cobre `=` OU `:`, com aspa simples OU dupla
# opcional de cada lado — sondado empiricamente contra os quatro casos antes
# de entrar aqui (ver tests abaixo).
_PARAMS_SENSIVEIS = re.compile(
    r"(access_token|appsecret_proof|client_secret)"  # nome
    r"([\"']?\s*[:=]\s*[\"']?)"  # separador: = ou :, com aspa simples/dupla opcional
    r"[^&\s\"']+",  # valor
    re.IGNORECASE,
)

# F190 / onda final — o redator era CEGO a forma que a propria branch criou.
# `_PARAMS_SENSIVEIS` so conhece `nome=valor` / `nome: valor`, a forma de QUERY
# STRING, que era o mundo antes da troca de transporte. Depois da Task 3 o
# token viaja em `Authorization: Bearer <token>`, e as tres formas reais dele
# passavam INTACTAS (medido contra o codigo pre-fix):
#
#   'Authorization: Bearer EAAG_TOKEN_123'       -> INALTERADO
#   'authorization: Bearer EAAG_TOKEN_123'       -> INALTERADO
#   "{'authorization': 'Bearer EAAG_TOKEN_123'}" -> INALTERADO
#
# A camada 2 existe pra cobrir o caminho que ninguem previu, e estava cega ao
# caminho que a camada 1 tinha acabado de criar.
#
# ANCORADO NO ESQUEMA (`Bearer`), NAO NO NOME DO CABECALHO — e a diferenca
# entre fechar e parecer que fechou. O reflexo obvio seria acrescentar
# `authorization` a alternacao de `_PARAMS_SENSIVEIS`; medido, isso produz
# `Authorization: <REDIGIDO> EAAG_TOKEN_123`: a classe de valor daquele regex
# (`[^&\s"']+`) para no primeiro espaco, entao ela redige o literal "Bearer" e
# deixa o TOKEN INTEIRO passar — pior que nao cobrir, porque o `<REDIGIDO>` no
# meio da linha parece cobertura. Nas tres formas o token vem sempre DEPOIS do
# esquema; ancorar nele pega as tres com um padrao so, e o nome do cabecalho
# sobrevive por ficar de fora do casamento.
#
# O esquema tambem sobrevive (`Bearer <REDIGIDO>`): mesma razao de preservar o
# nome do parametro — quem le o log precisa saber QUE tipo de credencial estava
# ali. A classe de valor exclui aspas, virgula e `}` alem do espaco, pra nao
# comer o fechamento do dict/JSON em `{'authorization': 'Bearer X'}`.
_CREDENCIAL_EM_HEADER = re.compile(
    r"(Bearer\s+)"  # esquema (diagnostico: sobrevive)
    r"[^\s\"',}&]+",  # valor = a credencial
    re.IGNORECASE,
)


def _redigir(texto: str) -> str:
    """Troca o VALOR de credencial por `<REDIGIDO>`, preservando nome e esquema.

    Preserva o nome de proposito: quem le o log precisa saber QUE havia um token
    ali — apagar o par inteiro esconderia a propria ocorrencia do problema.

    Duas formas cobertas, porque as duas existem em producao: `nome=valor` /
    `{"nome": "valor"}` (query string e JSON, via `_PARAMS_SENSIVEIS`) e
    `Authorization: Bearer <valor>` (via `_CREDENCIAL_EM_HEADER`, a forma que o
    transporte novo usa).

    O que esta denylist NAO alcanca: qualquer credencial que nao esteja
    imediatamente colada a um dos nomes reconhecidos via `=`/`:`, nem depois de
    um esquema `Bearer`. Em particular, token citado em PROSA pela propria API
    Graph — por exemplo `"Cannot parse access token: X"` (formato real de erro)
    usa "access token" com espaco, nao o literal `access_token` — nao tem a
    ancora que estes regex procuram, e nenhuma denylist por nome chega la.
    Essa e a razao de esta camada ser a SEGUNDA linha de defesa, nao a unica:
    a primeira (Task 3) e o transporte nunca por o token na URL/corpo em
    primeiro lugar.
    """
    return _CREDENCIAL_EM_HEADER.sub(
        r"\1<REDIGIDO>", _PARAMS_SENSIVEIS.sub(r"\1\2<REDIGIDO>", texto)
    )


@dataclass(slots=True, frozen=True)
class MetaAdsFriendlyError(Exception):
    message: str
    retryable: bool


def _do_envelope_de_erro(
    code: int | None, subcode: int | None, mensagem: str | None
) -> MetaAdsFriendlyError | None:
    """A TABELA CURADA, aplicada ao envelope `{"error": {...}}` da Graph API.

    Devolve `None` quando o corpo nao trouxe envelope nenhum (corpo vazio, HTML
    de intermediario, JSON sem a chave `error`) — ai quem chama volta pro texto
    cru com o status HTTP, que e o unico diagnostico que sobrou.

    Esta tabela so existia no ramo do SDK (`FacebookRequestError`). A troca de
    transporte da Task 3 tirou o SDK do caminho de request e o ramo ficou SEM
    PRODUTOR — com ~10 testes verdes por cima. Na pratica, um throttle Meta
    chegava ao gestor como JSON cru em ingles truncado em 200 chars e
    `retryable=False`: exatamente o estado que a PR 6 dizia ter corrigido.
    O produtor agora e `MetaGraphHTTPError`, que le `code`/`error_subcode`/
    `message` do corpo.
    """
    if code is None and subcode is None:
        return None
    if subcode in SUBCODES_DE_CONEXAO_EXPIRADA:
        return MetaAdsFriendlyError(
            "Sua conexão Meta expirou ou foi revogada. Reconecte via painel admin.",
            retryable=False,
        )
    if subcode == 2635 or code in CODIGOS_DE_THROTTLE:
        return MetaAdsFriendlyError(
            "Limite Meta atingido. Tente novamente em alguns minutos.",
            retryable=True,
        )
    if code == 190:
        return MetaAdsFriendlyError(
            "Permissão insuficiente. Verifique se aceitou ads_read + ads_management.",
            retryable=False,
        )
    if code == 100:
        return MetaAdsFriendlyError(
            f"Campo inválido na requisição Meta: {_redigir(str(mensagem))}",
            retryable=False,
        )
    return MetaAdsFriendlyError(
        f"Erro Meta API ({code}/{subcode}): {_redigir(str(mensagem))}",
        retryable=False,
    )


def to_friendly_meta_error(e: Exception) -> MetaAdsFriendlyError:
    """Map Graph API exceptions to PT-BR messages.

    `MetaGraphHTTPError` — o unico produtor real desde a Task 3 — passa pela
    tabela curada de `_do_envelope_de_erro`; qualquer outra excecao cai no
    fallback generico. Toda mensagem sai por `_redigir`.

    Nao ha mais ramo de `FacebookRequestError`: o SDK saiu do caminho de
    request, entao aquele ramo ficou sem produtor. Import tardio de
    `MetaGraphHTTPError` porque `reports` importa `errors` no topo — o caminho
    inverso tem de ser preguicoso pra nao fechar o ciclo.
    """
    from src.meta_ads.reports import MetaGraphHTTPError  # noqa: PLC0415

    if isinstance(e, MetaGraphHTTPError):
        curado = _do_envelope_de_erro(e.code, e.subcode, e.mensagem)
        if curado is None:
            return MetaAdsFriendlyError(_redigir(str(e)), retryable=e.retryable)
        # UNIAO, nao substituicao: a tabela curada pode GANHAR retryable (um
        # throttle vem em 4xx, e o status sozinho diria "permanente"), mas
        # nunca PERDE o que o status ja afirmava — um 5xx e transitorio por
        # definicao, qualquer que seja o code que o Graph tenha posto no corpo.
        return MetaAdsFriendlyError(curado.message, retryable=curado.retryable or e.retryable)

    return MetaAdsFriendlyError(f"Erro inesperado: {_redigir(str(e))}", retryable=False)
