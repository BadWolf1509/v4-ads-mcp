"""Integration tests for the OAuth flow with respx mocks."""

from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
import respx
from httpx import AsyncClient, Response

from src.auth.oauth_state import sign_state, verify_state
from src.auth.panel_session import PANEL_SESSION_COOKIE_NAME, verify_panel_session
from src.db import connection
from src.db.repositories import google_oauth_connections, managers
from tests.integration._audiencia import audiencia_crua, state_da_url

_SIGNING_KEY = "x" * 32
_AES_MASTER = "y" * 43  # urlsafe base64 source for 32 bytes


@pytest.mark.integration
async def test_start_redirects_to_google(client: AsyncClient) -> None:
    # Bootstrap a manager.
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="boot@v4.com", full_name="Boot")
    invite = sign_state({"manager_id": str(mid)}, _SIGNING_KEY, aud="cli_invite")

    response = await client.get(f"/oauth/google/start?invite={invite}", follow_redirects=False)
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    qs = parse_qs(urlparse(location).query)
    scope_str = qs["scope"][0]
    assert "adwords" in scope_str
    assert "userinfo.email" in scope_str
    assert "openid" in scope_str
    assert qs["access_type"] == ["offline"]
    assert qs["prompt"] == ["consent"]


@pytest.mark.integration
async def test_start_rejects_invalid_invite(client: AsyncClient) -> None:
    response = await client.get("/oauth/google/start?invite=bogus", follow_redirects=False)
    assert response.status_code == 400


@pytest.mark.integration
@respx.mock
async def test_callback_persists_encrypted_refresh_token(client: AsyncClient) -> None:
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="cb@v4.com", full_name=None)

    state = sign_state({"manager_id": str(mid)}, _SIGNING_KEY, aud="google_oauth")

    # Mock Google's token + userinfo endpoints.
    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=Response(
            200,
            json={
                "access_token": "ya29.fake",
                "refresh_token": "1//06fake-refresh",
                "expires_in": 3600,
                "scope": "https://www.googleapis.com/auth/adwords",
                "token_type": "Bearer",
            },
        )
    )
    respx.get("https://www.googleapis.com/oauth2/v2/userinfo").mock(
        return_value=Response(200, json={"email": "manager@v4company.com"})
    )

    response = await client.get(
        f"/oauth/google/callback?code=fake-code&state={state}",
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "Conectado" in response.text

    # Verify the connection was persisted with encrypted refresh token.
    async with pool.acquire() as conn:
        c = await google_oauth_connections.get_active_for_manager(conn, mid)
    assert c is not None
    assert c.google_email == "manager@v4company.com"
    assert c.refresh_token_enc != b"1//06fake-refresh"  # encrypted, not plaintext
    assert len(c.refresh_token_enc) > 16  # nonce + ct + tag


@pytest.mark.integration
async def test_callback_rejects_missing_refresh_token(client: AsyncClient) -> None:
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="nr@v4.com", full_name=None)
    state = sign_state({"manager_id": str(mid)}, _SIGNING_KEY, aud="google_oauth")

    with respx.mock:
        respx.post("https://oauth2.googleapis.com/token").mock(
            return_value=Response(200, json={"access_token": "x"})  # no refresh_token
        )
        response = await client.get(
            f"/oauth/google/callback?code=fake&state={state}",
            follow_redirects=False,
        )
    assert response.status_code == 400
    assert "refresh_token" in response.text


@pytest.mark.integration
async def test_callback_rejects_google_error(client: AsyncClient) -> None:
    response = await client.get(
        "/oauth/google/callback?error=access_denied",
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "access_denied" in response.text


@pytest.mark.integration
@respx.mock
async def test_callback_rejects_non_v4_email(client: AsyncClient) -> None:
    """OAuth callback must 403 when the userinfo email isn't @v4company.com."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="d@v4.com", full_name=None)
    state = sign_state({"manager_id": str(mid)}, _SIGNING_KEY, aud="google_oauth")

    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=Response(
            200,
            json={
                "access_token": "ya29.fake",
                "refresh_token": "1//06fake",
                "expires_in": 3600,
                "scope": "openid https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/adwords",
                "token_type": "Bearer",
            },
        )
    )
    respx.get("https://www.googleapis.com/oauth2/v2/userinfo").mock(
        return_value=Response(200, json={"email": "attacker@gmail.com"}),
    )

    response = await client.get(
        f"/oauth/google/callback?code=fake&state={state}",
        follow_redirects=False,
    )
    assert response.status_code == 403
    assert "v4company.com" in response.text


# ---------------------------------------------------------------------------
# Audiência dos call-sites que ASSINAM (revisão da Task 4, Importante 1)
#
# Os lados de verificação já estavam presos por testes de rota; os de assinatura
# não estavam por nada. Uma troca entre dois valores VÁLIDOS do `Literal`
# (`"panel"` onde devia ser `"google_oauth"`) passa no `mypy --strict` — os dois
# são `Audience` — e passava na suíte inteira, aparecendo só em produção como
# fluxo que não autentica. O `Literal` pega o typo; só teste pega a troca.
#
# Por isso estes testes leem a claim do CORPO do token (`audiencia_crua`) em vez
# de chamar `verify_state`: os verificadores removem `aud` do payload devolvido,
# e `verify_state(t, k, aud=X)` responde só "casa com X" — não diz o que o
# call-site escreveu.
# ---------------------------------------------------------------------------


def _set_cookie_de(response: Response, nome: str) -> str:
    """Valor cru do cookie `nome` no cabeçalho Set-Cookie da resposta.

    Lido do cabeçalho e não de `response.cookies` porque o cookie de painel é
    `Secure` e o cliente de teste fala http — o jar do httpx o descartaria.
    """
    for raw in response.headers.get_list("set-cookie"):
        if raw.startswith(f"{nome}="):
            return raw.split(";", 1)[0].split("=", 1)[1]
    raise AssertionError(f"Set-Cookie sem `{nome}`: {response.headers.get_list('set-cookie')!r}")


@pytest.mark.integration
async def test_start_panel_login_assina_state_com_audiencia_google_oauth(
    client: AsyncClient,
) -> None:
    """`/start?mode=panel_login` assina o state para o callback do Google (`oauth.py:157`).

    O state emitido aqui é conferido em `/callback` com `aud="google_oauth"`;
    qualquer outra audiência quebraria o login de painel inteiro.
    """
    response = await client.get("/oauth/google/start?mode=panel_login", follow_redirects=False)
    assert response.status_code == 302

    state = state_da_url(response.headers["location"])
    assert audiencia_crua(state) == "google_oauth"
    # E o par fecha: quem confere aceita o que este lado assinou.
    assert verify_state(state, _SIGNING_KEY, aud="google_oauth") == {"mode": "panel_login"}


@pytest.mark.integration
async def test_start_com_invite_assina_state_com_audiencia_google_oauth(
    client: AsyncClient,
) -> None:
    """O ramo de convite do `/start` reassina para o callback, não repassa o convite
    (`oauth.py:189`).

    Duas audiências convivem nesta rota: entra `cli_invite` (o convite da CLI) e
    sai `google_oauth` (o state do callback). Trocar uma pela outra é a confusão
    exata que este PR fecha — o convite valendo como token de outro propósito.
    """
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="aud@v4.com", full_name=None)
    invite = sign_state({"manager_id": str(mid)}, _SIGNING_KEY, aud="cli_invite")

    response = await client.get(f"/oauth/google/start?invite={invite}", follow_redirects=False)
    assert response.status_code == 302

    state = state_da_url(response.headers["location"])
    assert audiencia_crua(state) == "google_oauth"
    assert state != invite, "o convite não pode ser repassado verbatim como state do callback"
    assert verify_state(state, _SIGNING_KEY, aud="google_oauth") == {"manager_id": str(mid)}


@pytest.mark.integration
@respx.mock
async def test_callback_panel_login_emite_cookie_com_audiencia_panel(client: AsyncClient) -> None:
    """O ramo `mode=panel_login` do `/callback` emite o cookie de painel (`oauth.py:369`).

    Este é o único caminho de produção que assina cookie de painel, e nenhum
    teste o percorria: os três testes de `/callback` mandam `{"manager_id": …}`
    sem `mode`, tomam o ramo da CLI e param na página de sucesso.
    """
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(
            conn, manager_id=mid, email="painel@v4company.com", full_name="Painel"
        )

    state = sign_state({"mode": "panel_login"}, _SIGNING_KEY, aud="google_oauth")

    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=Response(
            200,
            json={
                "access_token": "ya29.fake",
                "refresh_token": "1//06fake-refresh",
                "expires_in": 3600,
                "scope": "https://www.googleapis.com/auth/adwords",
                "token_type": "Bearer",
            },
        )
    )
    respx.get("https://www.googleapis.com/oauth2/v2/userinfo").mock(
        return_value=Response(200, json={"email": "painel@v4company.com", "id": "42"})
    )

    response = await client.get(
        f"/oauth/google/callback?code=fake-code&state={state}",
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/"

    cookie = _set_cookie_de(response, PANEL_SESSION_COOKIE_NAME)
    assert audiencia_crua(cookie) == "panel"
    # E o par fecha: `deps._resolve_session` aceita o que este lado assinou.
    sessao = verify_panel_session(cookie, _SIGNING_KEY, aud="panel")
    assert sessao.manager_id == str(mid)
    assert sessao.email == "painel@v4company.com"
