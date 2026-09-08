"""Unit tests for Meta error → PT-BR friendly mapping (Sprint M.2a Task 6).

A familia de throttle do Graph e maior que o code 4.

Antes: 4 e subcode 2635 eram retryable; 17, 613 e 80004 caiam no ramo generico
com retryable=False. Throttle transitorio virava falha permanente na cara do
gestor, e nenhum caminho de retry disparava.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.meta_ads.errors import MetaAdsFriendlyError, to_friendly_meta_error

facebook_business = pytest.importorskip("facebook_business")
from facebook_business.exceptions import FacebookRequestError  # noqa: E402


def _build_fb_error(*, code=None, subcode=None, message="error msg"):
    """Construct a fake FacebookRequestError-like mock with the required methods."""
    err = MagicMock()
    err.api_error_code = MagicMock(return_value=code)
    err.api_error_subcode = MagicMock(return_value=subcode)
    err.api_error_message = MagicMock(return_value=message)
    from facebook_business.exceptions import FacebookRequestError

    err.__class__ = FacebookRequestError
    return err


def _erro(code: int, subcode: int | None = None, msg: str = "limite") -> FacebookRequestError:
    corpo = {"error": {"code": code, "message": msg}}
    if subcode is not None:
        corpo["error"]["error_subcode"] = subcode
    return FacebookRequestError(
        message=msg,
        request_context={},
        http_status=400,
        http_headers={},
        body=corpo,
    )


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


@pytest.mark.parametrize("code", [4, 17, 613, 80004])
def test_toda_a_familia_de_throttle_e_retryable(code: int) -> None:
    r = to_friendly_meta_error(_erro(code))
    assert r.retryable is True, f"code {code} deveria ser retryable"
    assert "limite" in r.message.lower(), f"code {code}: mensagem nao fala de limite"


def test_subcode_2635_continua_retryable() -> None:
    assert to_friendly_meta_error(_erro(1, subcode=2635)).retryable is True


@pytest.mark.parametrize("code", [190, 100, 200, 3018])
def test_o_que_nao_e_throttle_continua_nao_retryable(code: int) -> None:
    """Contraprova: sem ela, `retryable=True` incondicional passaria verde.

    Um guard que so afirma o lado positivo nao distingue "classifica throttle"
    de "diz sim para tudo".
    """
    assert to_friendly_meta_error(_erro(code)).retryable is False
