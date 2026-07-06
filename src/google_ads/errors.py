"""Translate Google Ads SDK exceptions into PT-BR friendly errors.

Phase 1a covers only the few errors the resync + list_my_accounts paths
can hit. Future phases extend this dict.
"""

from typing import Any

from src.auth.tokens import InvalidCiphertextError
from src.config import get_settings


class GoogleAdsFriendlyError(Exception):
    """User-facing error with a PT-BR message + the original exception attached."""

    def __init__(
        self, message_pt: str, *, code: str | None = None, original: Exception | None = None
    ):
        super().__init__(message_pt)
        self.message_pt = message_pt
        self.code = code
        self.original = original


# Map of (error_code, error_string_in_proto) → friendly PT-BR message.
# The Google Ads SDK exposes errors as GoogleAdsException.failure.errors[].error_code
# which is a oneof — we look at the populated field name.
_FRIENDLY_MESSAGES: dict[str, str] = {
    "AUTHENTICATION_ERROR": (
        "Falha de autenticação com o Google Ads. A conexão OAuth do gestor pode "
        "ter sido revogada — peça pra ele reconectar."
    ),
    "AUTHORIZATION_ERROR": (
        "Sem permissão pra esta operação. Verifique se o gestor tem acesso ao "
        "MCC e às contas em questão."
    ),
    "QUOTA_ERROR": (
        "Quota diária da API do Google Ads esgotada (15.000 ops). Aguarde o "
        "reset de meia-noite (PT) ou solicite Standard Access."
    ),
    "INTERNAL_ERROR": ("Erro interno do Google Ads. Tente novamente em alguns segundos."),
}


# Policy topics do classificador AUTOMÁTICO de texto do Google que geram
# falso-positivo em português legítimo com acento (investigação 2026-07-06 / A7:
# a MESMA conta tinha anúncios acentuados APROVADOS enquanto copy quase-idêntica
# com acento era reprovada — logo acento NÃO é o gatilho determinístico). Pra estes
# tópicos orientamos retry/revisão manual em vez de mandar o gestor "remover o que
# viola" (guidance que o empurra a tirar os acentos por engano).
_CLASSIFIER_PRONE_TOPICS = ("UNACCEPTABLE_SPACING", "SYMBOLS")


def _extract_policy_topics(error: Any) -> list[str]:
    """Best-effort: nomes dos policy topics de um GoogleAdsError policy_finding_error.

    Estrutura: error.details.policy_finding_details.policy_topic_entries[].topic.
    Tudo via getattr → degrada pra [] se o proto mudar entre versões do SDK.
    """
    details = getattr(error, "details", None)
    pfd = getattr(details, "policy_finding_details", None) if details is not None else None
    entries = getattr(pfd, "policy_topic_entries", None) if pfd is not None else None
    if not entries:
        return []
    return [str(getattr(e, "topic", "")) for e in entries if getattr(e, "topic", "")]


def to_friendly(exc: Exception) -> GoogleAdsFriendlyError:
    """Convert a GoogleAdsException to a friendly PT-BR error.

    If the SDK exception's structure can't be parsed, returns a generic message
    with the original exception attached.
    """
    # Idempotente: se já é um erro amigável (ex.: build_client_for_manager já
    # converteu um decrypt-failure), devolve como está — re-embrulhar perderia a
    # mensagem PT-BR curada num genérico "Erro inesperado".
    if isinstance(exc, GoogleAdsFriendlyError):
        return exc

    # Token decrypt failure: o refresh token do gestor não pode ser decifrado
    # (AES master key rotacionada — a migração GCP 2026-06-30 regenerou a chave).
    # Mensagem PT-BR acionável apontando pra reconexão; sem isto o dispatcher
    # scruba pra "Erro interno" genérico e o gestor fica travado no cutover (F70).
    if isinstance(exc, InvalidCiphertextError):
        base_url = get_settings().public_base_url
        return GoogleAdsFriendlyError(
            "Sua conexão Google Ads precisa ser refeita: as chaves de segurança "
            "mudaram (migração) e o token salvo não pode mais ser lido. Acesse "
            f"{base_url} e reconecte sua conta Google no painel.",
            code="TOKEN_DECRYPT_FAILED",
            original=exc,
        )

    # Avoid importing the Google SDK here to keep this module testable in isolation.
    failure = getattr(exc, "failure", None)
    if failure is None:
        # Include exception class name in the user-visible message so the
        # symptom carries one bit of diagnostic info even before logs are
        # consulted. The full traceback is captured upstream via log.exception.
        exc_type_name = type(exc).__name__
        return GoogleAdsFriendlyError(
            f"Erro inesperado ao falar com o Google Ads ({exc_type_name}).",
            original=exc,
        )

    errors = getattr(failure, "errors", None) or []
    if not errors:
        return GoogleAdsFriendlyError(
            "O Google Ads recusou a operação sem detalhes.",
            original=exc,
        )

    first = errors[0]
    error_code = getattr(first, "error_code", None)
    populated = None
    if error_code is not None:
        # error_code is a proto oneof — find which field is set.
        for field_name in (
            "authentication_error",
            "authorization_error",
            "quota_error",
            "internal_error",
            "query_error",
            "policy_finding_error",
        ):
            if getattr(error_code, field_name, None):
                populated = field_name.upper()
                break

    sdk_msg = getattr(first, "message", "erro desconhecido")

    if populated == "QUERY_ERROR":
        # GAQL field/metric/resource error. run_gaql é escape hatch: clientes LLM
        # chutam nomes de campo. Mantém o campo cru E anexa uma dica acionável pro
        # próximo turno se autocorrigir em vez de repetir o chute.
        msg = (
            f"Google Ads retornou: {sdk_msg} → Chame list_gaql_resources pros campos "
            "válidos e validate_gaql pra validar antes de rodar. Métricas existem só em "
            "certos recursos (ex.: impression share não sai em CUSTOMER) e auction "
            "insights (overlap rate, position above rate, outranking share) não existem "
            "na GAQL, só na UI do Google Ads."
        )
    elif populated == "POLICY_FINDING_ERROR":
        # RSA/anúncio reprovado por política. O sdk_msg genérico ("policy topics of
        # type PROHIBITED") não diz QUAL política — o gestor tentava às cegas (9x no
        # dogfood 07-02). Extrai os tópicos específicos pra ele saber o que corrigir.
        topics = _extract_policy_topics(first)
        if topics:
            topics_str = ", ".join(topics)
            if any(key in t for t in topics for key in _CLASSIFIER_PRONE_TOPICS):
                # Topics do classificador automático (spacing/symbols): frequentemente
                # falso-positivo em texto acentuado legítimo (A7). NÃO mandar remover
                # conteúdo — orienta retry/revisão manual pra não perder os acentos.
                msg = (
                    f"Google Ads reprovou o anúncio por política: {topics_str}. "
                    "Cheque espaçamento incomum (espaços duplos, letras separadas por "
                    "espaço) e símbolos ou pontuação repetidos (!!!, $$$). Se o texto "
                    "estiver correto, esse classificador automático às vezes gera "
                    "falso-positivo em português com acento: reenviar costuma resolver, "
                    "ou peça revisão manual no painel do Google Ads. "
                    "Detalhes: https://support.google.com/adspolicy."
                )
            else:
                msg = (
                    f"Google Ads reprovou o anúncio por política: {topics_str}. "
                    "Revise headlines/descriptions removendo o que viola essas políticas "
                    "e recrie. Detalhes: https://support.google.com/adspolicy."
                )
        else:
            msg = (
                f"Google Ads reprovou o anúncio por política: {sdk_msg} "
                "Revise headlines/descriptions e recrie."
            )
    else:
        # Fallback to the SDK's English message when there's no curated PT-BR one.
        friendly = _FRIENDLY_MESSAGES.get(populated or "")
        msg = friendly if friendly is not None else f"Google Ads retornou: {sdk_msg}"

    return GoogleAdsFriendlyError(msg, code=populated, original=exc)
