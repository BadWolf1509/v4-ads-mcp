"""Translate Google Ads SDK exceptions into PT-BR friendly errors.

Phase 1a covers only the few errors the resync + list_my_accounts paths
can hit. Future phases extend this dict.
"""


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
    # Avoid importing the Google SDK here to keep this module testable in isolation.
    failure = getattr(exc, "failure", None)
    if failure is None:
        return GoogleAdsFriendlyError(
            "Erro inesperado ao falar com o Google Ads.",
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
        ):
            if getattr(error_code, field_name, None):
                populated = field_name.upper()
                break

    msg = _FRIENDLY_MESSAGES.get(populated or "")
    if msg is None:
        # Fallback: include the SDK's English message.
        sdk_msg = getattr(first, "message", "erro desconhecido")
        msg = f"Google Ads retornou: {sdk_msg}"

    return GoogleAdsFriendlyError(msg, code=populated, original=exc)
