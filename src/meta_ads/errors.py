"""Map Meta API exceptions → PT-BR friendly errors for V4 gestores."""

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

# F190 — qualquer coisa que pareca credencial numa query string sai ANTES de a
# mensagem chegar a um sink. Cobre `access_token`, `appsecret_proof` e
# `client_secret`; o SDK injeta os dois primeiros sem opt-out
# (`FacebookSession.__init__`), e o terceiro aparece no fluxo OAuth.
#
# Denylist e reconhecidamente fraca — por isso ela e a SEGUNDA linha de defesa.
# A primeira e o transporte nao pôr o token na URL (Task 3). Esta existe porque
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


def _redigir(texto: str) -> str:
    """Troca o VALOR de parametro sensivel por `<REDIGIDO>`, preservando o nome.

    Preserva o nome de proposito: quem le o log precisa saber QUE havia um token
    ali — apagar o par inteiro esconderia a propria ocorrencia do problema.

    O que esta denylist NAO alcanca: qualquer credencial que nao esteja
    imediatamente colada a um dos tres nomes reconhecidos via `=` ou `:`. Em
    particular, token citado em PROSA pela propria API Graph — por exemplo
    `"Cannot parse access token: X"` (formato real de erro) usa "access token"
    com espaco, nao o literal `access_token` — nao tem a ancora `nome=`/`nome:`
    que este regex procura, e nenhuma denylist por nome de parametro chega la.
    Essa e a razao de esta camada ser a SEGUNDA linha de defesa, nao a unica:
    a primeira (Task 3) e o transporte nunca por o token na URL/corpo em
    primeiro lugar.
    """
    return _PARAMS_SENSIVEIS.sub(r"\1\2<REDIGIDO>", texto)


@dataclass(slots=True, frozen=True)
class MetaAdsFriendlyError(Exception):
    message: str
    retryable: bool


def to_friendly_meta_error(e: Exception) -> MetaAdsFriendlyError:
    """Map Meta SDK / Graph API exceptions to PT-BR messages.

    Handles FacebookRequestError variants. Falls back to generic error msg
    for unknown exception types.
    """
    try:
        from facebook_business.exceptions import FacebookRequestError  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        return MetaAdsFriendlyError(f"Erro inesperado: {_redigir(str(e))}", retryable=False)

    if isinstance(e, FacebookRequestError):
        subcode = e.api_error_subcode()
        code = e.api_error_code()
        message = e.api_error_message()

        if subcode in (458, 467, 460, 463):
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
                f"Campo inválido na requisição Meta: {_redigir(str(message))}",
                retryable=False,
            )
        return MetaAdsFriendlyError(
            f"Erro Meta API ({code}/{subcode}): {_redigir(str(message))}",
            retryable=False,
        )

    from src.meta_ads.reports import MetaGraphHTTPError  # noqa: PLC0415

    if isinstance(e, MetaGraphHTTPError):
        return MetaAdsFriendlyError(_redigir(str(e)), retryable=e.retryable)

    return MetaAdsFriendlyError(f"Erro inesperado: {_redigir(str(e))}", retryable=False)
