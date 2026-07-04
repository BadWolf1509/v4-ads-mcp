"""Unit tests for `to_friendly` (src/google_ads/errors.py) — categorias sem teste direto.

NOTA: tests/unit/test_google_ads_client.py já cobre to_friendly extensivamente
(authentication_error, quota_error, unknown fallback, no-failure, empty-errors,
ciphertext/F70, policy_finding com/sem topics, query_error/F62) — este arquivo
NÃO reimplementa esses casos. Fecha só os 2 gaps reais que restavam no dict
_FRIENDLY_MESSAGES sem cobertura: AUTHORIZATION_ERROR e INTERNAL_ERROR.

Usa o mesmo padrão de _FakeException/_FakeError/_FakeErrorCode de
test_google_ads_client.py (duck-typed, sem importar o SDK real).
"""

from src.google_ads.errors import to_friendly


class _FakeErrorCode:
    """Mimics the proto oneof — only the populated field is truthy."""

    def __init__(self, populated_field: str | None):
        for field in (
            "authentication_error",
            "authorization_error",
            "quota_error",
            "internal_error",
            "query_error",
            "policy_finding_error",
        ):
            setattr(self, field, 1 if field == populated_field else 0)


class _FakeError:
    def __init__(self, populated_field: str | None, message: str = "boom"):
        self.error_code = _FakeErrorCode(populated_field)
        self.message = message


class _FakeFailure:
    def __init__(self, errors):
        self.errors = errors


class _FakeException(Exception):  # noqa: N818
    def __init__(self, errors):
        super().__init__("fake")
        self.failure = _FakeFailure(errors)


def test_authorization_error_pt_message():
    fe = to_friendly(_FakeException([_FakeError("authorization_error")]))
    assert fe.code == "AUTHORIZATION_ERROR"
    assert "permissão" in fe.message_pt.lower()
    assert "MCC" in fe.message_pt


def test_internal_error_pt_message():
    fe = to_friendly(_FakeException([_FakeError("internal_error")]))
    assert fe.code == "INTERNAL_ERROR"
    assert "Erro interno do Google Ads" in fe.message_pt


def test_already_friendly_error_passes_through_unchanged():
    """Idempotência: um GoogleAdsFriendlyError já convertido não é re-embrulhado
    (re-wrap perderia a mensagem PT-BR curada por um genérico 'Erro inesperado')."""
    from src.google_ads.errors import GoogleAdsFriendlyError

    original = GoogleAdsFriendlyError("mensagem já amigável", code="TOKEN_DECRYPT_FAILED")
    fe = to_friendly(original)
    assert fe is original
    assert fe.message_pt == "mensagem já amigável"
    assert fe.code == "TOKEN_DECRYPT_FAILED"


def test_original_exception_is_attached():
    """O .original preserva a exceção crua pra logging/diagnóstico upstream."""
    exc = _FakeException([_FakeError("quota_error")])
    fe = to_friendly(exc)
    assert fe.original is exc
