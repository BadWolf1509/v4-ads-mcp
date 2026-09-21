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
_PARAMS_SENSIVEIS = re.compile(
    r"(access_token|appsecret_proof|client_secret)=[^&\s\"']+",
    re.IGNORECASE,
)


def _redigir(texto: str) -> str:
    """Troca o VALOR de parametro sensivel por `<REDIGIDO>`, preservando o nome.

    Preserva o nome de proposito: quem le o log precisa saber QUE havia um token
    ali — apagar o par inteiro esconderia a propria ocorrencia do problema.
    """
    return _PARAMS_SENSIVEIS.sub(r"\1=<REDIGIDO>", texto)


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

    return MetaAdsFriendlyError(f"Erro inesperado: {_redigir(str(e))}", retryable=False)
