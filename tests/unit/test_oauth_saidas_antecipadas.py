"""Caracteriza cada saida antecipada de `_concluir_callback` (status, corpo, cookies).

O callback troca o code, confere a conta e so entao grava. Cada recusa devolve uma
resposta propria e NAO pode gravar conexao nem emitir sessao; o cookie do nonce e
apagado em todas (o nonce ja conferiu quando `_concluir_callback` roda).
"""

from __future__ import annotations

from typing import Any

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from src.auth import oauth
from src.auth.oauth_state import sign_state
from src.auth.panel_session import PANEL_SESSION_COOKIE_NAME
from src.config import get_settings
from tests.unit.test_oauth_navegador import (
    _EMAIL,
    _NONCE_COOKIE,
    _Banco,
    _mock_google,
    _set_cookie,
    _state_de,
    banco,  # noqa: F401  (fixture)
    navegador,  # noqa: F401  (fixture)
)


def _cookies_apagados(resp: Any) -> str:
    return " | ".join(resp.headers.get_list("set-cookie"))


def _assert_nonce_apagado(resp: Any) -> None:
    bruto = _set_cookie(resp, _NONCE_COOKIE)
    assert "Max-Age=0" in bruto
    assert "Path=/oauth/google" in bruto or "path=/oauth/google" in bruto.lower()


def _state_com_nonce(navegador: TestClient, payload_extra: dict[str, Any]) -> str:  # noqa: F811
    """Assina um state com o nonce do cookie deste navegador, sem `mode` por padrao."""
    start = navegador.get("/oauth/google/start?mode=panel_login")
    nonce = _set_cookie(start, _NONCE_COOKIE).split(";")[0].split("=", 1)[1]
    return sign_state(
        {"nonce": nonce, **payload_extra}, get_settings().session_signing_key, aud="google_oauth"
    )


@respx.mock
def test_troca_do_code_falha_devolve_502(navegador: TestClient, banco: _Banco) -> None:  # noqa: F811
    respx.post(oauth.GOOGLE_TOKEN_URL).mock(return_value=Response(400, text="invalid_grant"))
    state = _state_de(navegador.get("/oauth/google/start?mode=panel_login"))

    resp = navegador.get("/oauth/google/callback", params={"code": "c", "state": state})

    assert resp.status_code == 502
    assert "Troca do code falhou (HTTP 400)" in resp.text
    assert banco.conexoes == []
    assert PANEL_SESSION_COOKIE_NAME not in _cookies_apagados(resp)
    _assert_nonce_apagado(resp)


@respx.mock
def test_sem_refresh_token_devolve_400(navegador: TestClient, banco: _Banco) -> None:  # noqa: F811
    respx.post(oauth.GOOGLE_TOKEN_URL).mock(return_value=Response(200, json={"access_token": "at"}))
    userinfo = respx.get(oauth.GOOGLE_USERINFO_URL).mock(return_value=Response(200, json={}))
    state = _state_de(navegador.get("/oauth/google/start?mode=panel_login"))

    resp = navegador.get("/oauth/google/callback", params={"code": "c", "state": state})

    assert resp.status_code == 400
    assert "não devolveu refresh_token" in resp.text
    assert not userinfo.called
    assert banco.conexoes == []
    assert PANEL_SESSION_COOKIE_NAME not in _cookies_apagados(resp)
    _assert_nonce_apagado(resp)


@respx.mock
def test_dominio_nao_autorizado_devolve_403(navegador: TestClient, banco: _Banco) -> None:  # noqa: F811
    _mock_google({"email": "alguem@outro.com", "verified_email": True})
    state = _state_de(navegador.get("/oauth/google/start?mode=panel_login"))

    resp = navegador.get("/oauth/google/callback", params={"code": "c", "state": state})

    assert resp.status_code == 403
    assert "alguem@outro.com" in resp.text
    assert "apenas @v4company.com" in resp.text
    assert banco.conexoes == []
    assert PANEL_SESSION_COOKIE_NAME not in _cookies_apagados(resp)
    _assert_nonce_apagado(resp)


@respx.mock
def test_gestor_nao_convidado_redireciona_para_acesso_negado(
    navegador: TestClient,  # noqa: F811
    banco: _Banco,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _sem_gestor(_c: Any, _email: str) -> Any:
        return None

    async def _tabela_cheia(_c: Any) -> int:
        return 1

    monkeypatch.setattr(oauth.managers, "get_by_email", _sem_gestor)
    monkeypatch.setattr(oauth.managers, "count_all", _tabela_cheia)
    _mock_google()
    state = _state_de(navegador.get("/oauth/google/start?mode=panel_login"))

    resp = navegador.get("/oauth/google/callback", params={"code": "c", "state": state})

    assert resp.status_code == 302
    assert resp.headers["location"] == "/access-denied?reason=not_invited"
    tentativa = _set_cookie(resp, "v4_attempted_email")
    assert tentativa.startswith(f'v4_attempted_email="{_EMAIL}";')
    assert "Max-Age=60" in tentativa
    assert "Path=/access-denied" in tentativa
    assert "HttpOnly" in tentativa
    assert "Secure" in tentativa
    assert "SameSite=lax" in tentativa
    assert banco.conexoes == []
    assert PANEL_SESSION_COOKIE_NAME not in _cookies_apagados(resp)
    _assert_nonce_apagado(resp)


@respx.mock
def test_state_sem_manager_id_nem_mode_devolve_400(
    navegador: TestClient,  # noqa: F811
    banco: _Banco,  # noqa: F811
) -> None:
    _mock_google()
    state = _state_com_nonce(navegador, {})

    resp = navegador.get("/oauth/google/callback", params={"code": "c", "state": state})

    assert resp.status_code == 400
    assert "State payload missing both manager_id and mode." in resp.text
    assert banco.conexoes == []
    assert PANEL_SESSION_COOKIE_NAME not in _cookies_apagados(resp)
    _assert_nonce_apagado(resp)
