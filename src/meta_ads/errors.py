"""Map Meta API exceptions → PT-BR friendly errors for V4 gestores."""

from dataclasses import dataclass


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
        return MetaAdsFriendlyError(f"Erro inesperado: {e}", retryable=False)

    if isinstance(e, FacebookRequestError):
        subcode = e.api_error_subcode()
        code = e.api_error_code()
        message = e.api_error_message()

        if subcode in (458, 467, 460, 463):
            return MetaAdsFriendlyError(
                "Sua conexão Meta expirou ou foi revogada. Reconecte via painel admin.",
                retryable=False,
            )
        if subcode == 2635 or code == 4:
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
                f"Campo inválido na requisição Meta: {message}",
                retryable=False,
            )
        return MetaAdsFriendlyError(
            f"Erro Meta API ({code}/{subcode}): {message}",
            retryable=False,
        )

    return MetaAdsFriendlyError(f"Erro inesperado: {e}", retryable=False)
