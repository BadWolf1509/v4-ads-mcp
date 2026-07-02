"""Translate Google Ads SDK exceptions into PT-BR friendly errors.

Phase 1a covers only the few errors the resync + list_my_accounts paths
can hit. Future phases extend this dict.
"""

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


def to_friendly(exc: Exception) -> GoogleAdsFriendlyError:
    """Convert a GoogleAdsException to a friendly PT-BR error.

    If the SDK exception's structure can't be parsed, returns a generic message
    with the original exception attached.
    """
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
    else:
        # Fallback to the SDK's English message when there's no curated PT-BR one.
        friendly = _FRIENDLY_MESSAGES.get(populated or "")
        msg = friendly if friendly is not None else f"Google Ads retornou: {sdk_msg}"

    return GoogleAdsFriendlyError(msg, code=populated, original=exc)
