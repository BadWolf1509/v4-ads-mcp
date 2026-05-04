"""Test friendly-error translation without importing the heavy SDK."""

from src.google_ads.errors import GoogleAdsFriendlyError, to_friendly


class _FakeErrorCode:
    """Mimics the proto oneof — only the populated field is truthy."""

    def __init__(self, populated_field: str | None):
        for field in (
            "authentication_error",
            "authorization_error",
            "quota_error",
            "internal_error",
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


def test_authentication_error_pt_message():
    fe = to_friendly(_FakeException([_FakeError("authentication_error")]))
    assert "OAuth do gestor pode" in fe.message_pt
    assert fe.code == "AUTHENTICATION_ERROR"


def test_quota_error_pt_message():
    fe = to_friendly(_FakeException([_FakeError("quota_error")]))
    assert "Quota diária" in fe.message_pt


def test_unknown_code_falls_back_to_sdk_message():
    fe = to_friendly(_FakeException([_FakeError(None, message="weird internal thing")]))
    assert "weird internal thing" in fe.message_pt


def test_no_failure_attribute_returns_generic():
    fe = to_friendly(Exception("naked"))
    assert "Erro inesperado" in fe.message_pt
    assert isinstance(fe, GoogleAdsFriendlyError)


def test_empty_errors_list_returns_generic():
    fe = to_friendly(_FakeException([]))
    assert "sem detalhes" in fe.message_pt
