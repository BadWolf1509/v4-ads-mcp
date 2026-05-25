"""Unit tests for Meta error → PT-BR friendly mapping (Sprint M.2a Task 6)."""

from unittest.mock import MagicMock

from src.meta_ads.errors import MetaAdsFriendlyError, to_friendly_meta_error


def _build_fb_error(*, code=None, subcode=None, message="error msg"):
    """Construct a fake FacebookRequestError-like mock with the required methods."""
    err = MagicMock()
    err.api_error_code = MagicMock(return_value=code)
    err.api_error_subcode = MagicMock(return_value=subcode)
    err.api_error_message = MagicMock(return_value=message)
    from facebook_business.exceptions import FacebookRequestError

    err.__class__ = FacebookRequestError
    return err


def test_expired_token_subcode_458():
    err = _build_fb_error(subcode=458)
    result = to_friendly_meta_error(err)
    assert isinstance(result, MetaAdsFriendlyError)
    assert "expirou" in result.message.lower() or "reconecte" in result.message.lower()
    assert result.retryable is False


def test_expired_token_subcode_467():
    err = _build_fb_error(subcode=467)
    result = to_friendly_meta_error(err)
    assert result.retryable is False


def test_rate_limit_subcode_2635():
    err = _build_fb_error(subcode=2635)
    result = to_friendly_meta_error(err)
    assert "limite" in result.message.lower()
    assert result.retryable is True


def test_rate_limit_code_4():
    err = _build_fb_error(code=4)
    result = to_friendly_meta_error(err)
    assert result.retryable is True


def test_permission_denied_code_190():
    err = _build_fb_error(code=190)
    result = to_friendly_meta_error(err)
    assert "permissão" in result.message.lower() or "permissao" in result.message.lower()
    assert result.retryable is False


def test_invalid_field_code_100():
    err = _build_fb_error(code=100, message="Field 'foo' not supported")
    result = to_friendly_meta_error(err)
    assert "campo" in result.message.lower() or "inválido" in result.message.lower()
    assert result.retryable is False


def test_unknown_falls_back_with_code_subcode():
    err = _build_fb_error(code=999, subcode=888, message="weird error")
    result = to_friendly_meta_error(err)
    assert "999" in result.message or "888" in result.message
    assert result.retryable is False


def test_non_facebook_exception_falls_back():
    e = ValueError("generic error")
    result = to_friendly_meta_error(e)
    assert "inesperado" in result.message.lower() or "generic error" in result.message
    assert result.retryable is False
