"""Unit tests for Meta error → PT-BR friendly mapping (Sprint M.2a Task 6).

A familia de throttle do Graph e maior que o code 4.

Antes: 4 e subcode 2635 eram retryable; 17, 613 e 80004 caiam no ramo generico
com retryable=False. Throttle transitorio virava falha permanente na cara do
gestor, e nenhum caminho de retry disparava.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

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


def test_meta_graph_http_error_retryable_mesmo_sem_o_sdk_instalado() -> None:
    """F190/Task 3, fix round 1 (achado B da revisao): MetaGraphHTTPError nao
    tem relacao NENHUMA com o SDK facebook_business — o ramo que o mapeia tem
    de vir ANTES do `try: from facebook_business.exceptions import ... except
    ImportError: return ...`.

    Antes: o ramo vivia DEPOIS daquele try/except. Se o import do SDK
    falhasse — ausente, quebrado, ou removido de vez pela Task 6, que esta
    tirando superficie do SDK — o `return` antecipado do `except ImportError`
    engolia o ramo inteiro, e um 503 (retryable de verdade) virava "Erro
    inesperado" com retryable=False. O MESMO bug que esta task existe pra
    fechar, reaberto por um caminho diferente.

    `patch.dict(sys.modules, {"facebook_business.exceptions": None})` forca o
    proximo `from facebook_business.exceptions import ...` a levantar
    ImportError, simulando o SDK ausente independente de ele estar de fato
    instalado neste ambiente.
    """
    from src.meta_ads.reports import MetaGraphHTTPError

    with patch.dict(sys.modules, {"facebook_business.exceptions": None}):
        resultado = to_friendly_meta_error(MetaGraphHTTPError(503, "Service Unavailable"))

    assert resultado.retryable is True, (
        "um MetaGraphHTTPError 5xx tem que continuar retryable mesmo quando o "
        "import do SDK falha — o ramo nao pode estar atras do try/except "
        "ImportError, que nao tem nada a ver com ele"
    )
    assert "503" in resultado.message
