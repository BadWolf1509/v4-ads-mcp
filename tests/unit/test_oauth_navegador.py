"""OAuth do Google preso ao navegador: de ponta a ponta, sem banco.

O `state` assinado prova que o servidor o emitiu, nao QUEM o iniciou: sem vinculo
com o navegador, um atacante completa o consentimento com a conta DELE e faz a
vitima abrir o callback (login CSRF). O nonce vai no state e num cookie, e os dois
precisam casar.

Login quebrado tranca todos os gestores, entao os fluxos felizes correm aqui pelo
caminho inteiro, `/start` ate o callback, com o jar de cookies do cliente em
https: o cookie e `Secure`, e em http o jar nao o devolveria (ha um teste que mede
exatamente isso, para este arquivo nao passar por nao enviar nada).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from src.auth import oauth
from src.auth.oauth_state import STATE_TTL_SECONDS, sign_state, verify_state
from src.auth.panel_session import PANEL_SESSION_COOKIE_NAME, verify_panel_session
from src.config import get_settings

_NONCE_COOKIE = "v4_oauth_nonce"
_EMAIL = "gestor@v4company.com"


@dataclass
class _Banco:
    """O que o fluxo toca do banco; `conexoes` e o efeito que o login nao pode ter."""

    gestor_id: UUID = field(default_factory=uuid4)
    conexoes: list[dict[str, Any]] = field(default_factory=list)


class _Conn:
    async def __aenter__(self) -> _Conn:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _Pool:
    def acquire(self) -> _Conn:
        return _Conn()


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> _Banco:
    b = _Banco()
    # O `y` * 32 do conftest nao decodifica em 32 bytes, e aqui o token e cifrado de fato.
    monkeypatch.setenv("AES_MASTER_KEY", "y" * 43)
    gestor = SimpleNamespace(id=b.gestor_id, status="active", is_active=True, role="manager")

    async def _get_by_id(_c: Any, _id: UUID) -> Any:
        return gestor

    async def _get_by_email(_c: Any, _email: str) -> Any:
        return gestor

    async def _count_all(_c: Any) -> int:
        return 1

    async def _upsert(_c: Any, **kw: Any) -> None:
        b.conexoes.append(kw)

    monkeypatch.setattr(oauth.connection, "get_pool", lambda: _Pool())
    monkeypatch.setattr(oauth.managers, "get_by_id", _get_by_id)
    monkeypatch.setattr(oauth.managers, "get_by_email", _get_by_email)
    monkeypatch.setattr(oauth.managers, "count_all", _count_all)
    monkeypatch.setattr(oauth.google_oauth_connections, "upsert", _upsert)
    return b


def _navegador_em(base_url: str) -> TestClient:
    # Import tardio: `src.app` cria a app no import e exige o env do conftest.
    from src.app import create_app  # noqa: PLC0415

    return TestClient(create_app(skip_db_init=True), base_url=base_url, follow_redirects=False)


@pytest.fixture
def navegador() -> Iterator[TestClient]:
    """Um navegador: jar proprio, em https, como a producao."""
    with _navegador_em("https://testserver") as c:
        yield c


def _mock_google(userinfo: dict[str, Any] | None = None) -> respx.Route:
    """Mocka token + userinfo; devolve a rota do token para provar se foi chamada."""
    rota = respx.post(oauth.GOOGLE_TOKEN_URL).mock(
        return_value=Response(200, json={"access_token": "at", "refresh_token": "rt"})
    )
    respx.get(oauth.GOOGLE_USERINFO_URL).mock(
        return_value=Response(
            200,
            json=userinfo if userinfo is not None else {"email": _EMAIL, "verified_email": True},
        )
    )
    return rota


def _state_de(resp: Any) -> str:
    assert resp.status_code == 302, resp.text
    return parse_qs(urlparse(resp.headers["location"]).query)["state"][0]


def _set_cookie(resp: Any, nome: str) -> str:
    for raw in resp.headers.get_list("set-cookie"):
        if raw.startswith(f"{nome}="):
            return str(raw)
    raise AssertionError(f"sem Set-Cookie de {nome}: {resp.headers.get_list('set-cookie')!r}")


def _state_assinado(payload: dict[str, Any]) -> str:
    return sign_state(payload, get_settings().session_signing_key, aud="google_oauth")


def _convite(gestor_id: UUID) -> str:
    return sign_state(
        {"manager_id": str(gestor_id)}, get_settings().session_signing_key, aud="cli_invite"
    )


# --- caminhos felizes, de ponta a ponta ---------------------------------------


@respx.mock
def test_login_de_painel_de_ponta_a_ponta(navegador: TestClient, banco: _Banco) -> None:
    _mock_google()
    state = _state_de(navegador.get("/oauth/google/start?mode=panel_login"))

    resp = navegador.get("/oauth/google/callback", params={"code": "c", "state": state})

    assert resp.status_code == 302
    assert resp.headers["location"] == "/"
    cookie = _set_cookie(resp, PANEL_SESSION_COOKIE_NAME).split(";")[0].split("=", 1)[1]
    sessao = verify_panel_session(cookie, get_settings().session_signing_key, aud="panel")
    assert sessao.manager_id == str(banco.gestor_id)
    assert [c["manager_id"] for c in banco.conexoes] == [banco.gestor_id]


@respx.mock
def test_convite_de_ponta_a_ponta(navegador: TestClient, banco: _Banco) -> None:
    """O convite da CLI passa pelo mesmo `/start` e o `manager_id` sobrevive no state."""
    _mock_google()
    state = _state_de(
        navegador.get("/oauth/google/start", params={"invite": _convite(banco.gestor_id)})
    )

    payload = verify_state(state, get_settings().session_signing_key, aud="google_oauth")
    assert payload["manager_id"] == str(banco.gestor_id)

    resp = navegador.get("/oauth/google/callback", params={"code": "c", "state": state})

    assert resp.status_code == 200, resp.text
    assert "Conectado" in resp.text
    assert [c["manager_id"] for c in banco.conexoes] == [banco.gestor_id]


@pytest.mark.parametrize("fluxo", ["painel", "convite"])
def test_cookie_do_nonce_e_o_combinado(navegador: TestClient, banco: _Banco, fluxo: str) -> None:
    """HttpOnly, Secure, 10 min. `Lax` e nao `Strict`: o retorno vem do dominio do
    Google, e so o Lax acompanha navegacao top-level vinda de outro site."""
    params = {"mode": "panel_login"} if fluxo == "painel" else {"invite": _convite(banco.gestor_id)}
    resp = navegador.get("/oauth/google/start", params=params)

    bruto = _set_cookie(resp, _NONCE_COOKIE)
    atributos = {p.strip().lower() for p in bruto.split(";")[1:]}
    assert {"httponly", "secure", "samesite=lax", f"max-age={STATE_TTL_SECONDS}"} <= atributos
    # O cookie casa com o nonce que foi no state.
    valor = bruto.split(";")[0].split("=", 1)[1]
    payload = verify_state(_state_de(resp), get_settings().session_signing_key, aud="google_oauth")
    assert payload["nonce"] == valor


def test_retorno_do_google_e_get_top_level(navegador: TestClient) -> None:
    """SameSite=Lax so envia o cookie em navegacao top-level GET. `form_post` faria o
    Google voltar com POST cross-site, sem o cookie: todo login seria recusado."""
    resp = navegador.get("/oauth/google/start?mode=panel_login")
    qs = parse_qs(urlparse(resp.headers["location"]).query)

    assert "response_mode" not in qs
    assert qs["response_type"] == ["code"]
    assert navegador.post("/oauth/google/callback").status_code == 405


# --- recusas: nenhuma chega a trocar o code -----------------------------------


@respx.mock
def test_callback_sem_cookie_e_recusado(navegador: TestClient, banco: _Banco) -> None:
    """O ataque: state legitimo do atacante, aberto no navegador da vitima."""
    rota = _mock_google()
    state = _state_assinado({"mode": "panel_login", "nonce": "n" * 43})

    resp = navegador.get("/oauth/google/callback", params={"code": "c", "state": state})

    assert resp.status_code == 400
    assert "navegador" in resp.text
    assert not rota.called
    assert banco.conexoes == []
    assert PANEL_SESSION_COOKIE_NAME not in resp.headers.get("set-cookie", "")


@respx.mock
def test_cookie_secure_nao_volta_em_http(banco: _Banco) -> None:
    """Controle do arquivo: prova que o jar respeita `Secure`, logo os testes felizes
    acima so passam porque o cookie foi mesmo devolvido."""
    rota = _mock_google()
    with _navegador_em("http://testserver") as c:
        state = _state_de(c.get("/oauth/google/start?mode=panel_login"))
        resp = c.get("/oauth/google/callback", params={"code": "c", "state": state})

    assert resp.status_code == 400
    assert not rota.called


@respx.mock
def test_nonce_divergente_e_recusado(navegador: TestClient, banco: _Banco) -> None:
    rota = _mock_google()
    _state_de(navegador.get("/oauth/google/start?mode=panel_login"))
    state_alheio = _state_assinado({"mode": "panel_login", "nonce": "outro"})

    resp = navegador.get("/oauth/google/callback", params={"code": "c", "state": state_alheio})

    assert resp.status_code == 400
    assert not rota.called


@respx.mock
def test_state_sem_nonce_e_recusado(navegador: TestClient, banco: _Banco) -> None:
    """O state de antes deste fix (ou um sem a claim) nao vale, mesmo com cookie."""
    rota = _mock_google()
    _state_de(navegador.get("/oauth/google/start?mode=panel_login"))
    state = _state_assinado({"mode": "panel_login"})

    resp = navegador.get("/oauth/google/callback", params={"code": "c", "state": state})

    assert resp.status_code == 400
    assert not rota.called


@respx.mock
def test_cookie_nao_ascii_e_recusado_sem_500(navegador: TestClient, banco: _Banco) -> None:
    """`hmac.compare_digest` levanta TypeError em str nao ASCII, e o cookie e do cliente."""
    rota = _mock_google()
    state = _state_assinado({"mode": "panel_login", "nonce": "abc"})

    resp = navegador.get(
        "/oauth/google/callback",
        params={"code": "c", "state": state},
        headers={"cookie": f"{_NONCE_COOKIE}=\xe9".encode("latin-1")},  # type: ignore[dict-item]
    )

    assert resp.status_code == 400
    assert not rota.called


@respx.mock
def test_nonce_vale_uma_vez_so(navegador: TestClient, banco: _Banco) -> None:
    _mock_google()
    state = _state_de(navegador.get("/oauth/google/start?mode=panel_login"))
    primeiro = navegador.get("/oauth/google/callback", params={"code": "c", "state": state})
    assert primeiro.status_code == 302

    segundo = navegador.get("/oauth/google/callback", params={"code": "c", "state": state})

    assert segundo.status_code == 400
    assert len(banco.conexoes) == 1


@respx.mock
def test_tentativa_recusada_nao_derruba_o_login_em_curso(
    navegador: TestClient, banco: _Banco
) -> None:
    """Sem isto, um link forjado apagaria o cookie de quem esta no meio do login."""
    _mock_google()
    state = _state_de(navegador.get("/oauth/google/start?mode=panel_login"))
    forjado = _state_assinado({"mode": "panel_login", "nonce": "outro"})

    recusado = navegador.get("/oauth/google/callback", params={"code": "c", "state": forjado})
    assert recusado.status_code == 400

    resp = navegador.get("/oauth/google/callback", params={"code": "c", "state": state})
    assert resp.status_code == 302


# --- e-mail verificado --------------------------------------------------------


@respx.mock
def test_email_nao_verificado_e_recusado(navegador: TestClient, banco: _Banco) -> None:
    _mock_google({"email": _EMAIL, "verified_email": False})
    state = _state_de(navegador.get("/oauth/google/start?mode=panel_login"))

    resp = navegador.get("/oauth/google/callback", params={"code": "c", "state": state})

    assert resp.status_code == 403
    assert "verificado" in resp.text
    assert banco.conexoes == []
    assert PANEL_SESSION_COOKIE_NAME not in resp.headers.get("set-cookie", "")


@respx.mock
def test_verified_email_ausente_segue(
    navegador: TestClient, banco: _Banco, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O discovery do oauth2 v2 declara `verified_email` com `default: true` (conferido
    em 30/10), entao ausente e verificado no contrato do Google. Exigir `True` trancaria
    todos os gestores se a resposta omitir o default."""
    from src.auth import oauth as oauth_mod

    avisos: list[tuple[str, dict[str, Any]]] = []

    class _Log:
        def warning(self, evento: str, **kw: Any) -> None:
            avisos.append((evento, kw))

        def __getattr__(self, _nome: str) -> Any:
            return lambda *_a, **_k: None

    monkeypatch.setattr(oauth_mod, "log", _Log())
    _mock_google({"email": _EMAIL})
    state = _state_de(navegador.get("/oauth/google/start?mode=panel_login"))

    resp = navegador.get("/oauth/google/callback", params={"code": "c", "state": state})

    assert resp.status_code == 302
    assert resp.headers["location"] == "/"
    # Ausente segue, mas deixa rastro; o e-mail nao entra no log.
    assert [e for e, _ in avisos] == ["oauth_verified_email_ausente"]
    assert _EMAIL not in repr(avisos)


# --- superficie publica -------------------------------------------------------


@pytest.mark.parametrize("rota", ["/docs", "/redoc", "/openapi.json"])
def test_documentacao_da_api_nao_e_publica(navegador: TestClient, rota: str) -> None:
    assert navegador.get(rota).status_code == 404
