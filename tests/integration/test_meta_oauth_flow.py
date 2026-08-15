"""Integration tests for Meta OAuth callback flow via respx (Sprint M.2a Task 8)."""

from uuid import uuid4

import pytest
import respx
from httpx import AsyncClient, Response

from src.auth.oauth_state import sign_state
from src.db import connection
from src.db.repositories import manager_meta_account_access, managers, meta_oauth_connections

_SIGNING_KEY = "x" * 32
_AES_MASTER = "y" * 43  # urlsafe base64 source for 32 bytes


@pytest.fixture(autouse=True)
def _meta_env(monkeypatch):
    """Env extra além do padrão do conftest (DATABASE_URL/SESSION_SIGNING_KEY/AES_MASTER_KEY)."""
    monkeypatch.setenv("META_APP_ID", "test_app_id")
    monkeypatch.setenv("META_APP_SECRET", "test_app_secret")


def _make_state(manager_id: str) -> str:
    return sign_state(
        {"manager_id": manager_id, "aud": "meta_oauth"},
        _SIGNING_KEY,
    )


@pytest.mark.integration
@respx.mock
async def test_oauth_callback_happy_path(client: AsyncClient) -> None:
    """Full happy path: short token → long token → /me → debug_token → /me/adaccounts."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="ok@v4company.com", full_name="Ok")

    state = _make_state(str(mid))

    # F82: a troca short→long-lived deixou de ser GET com o `client_secret` na
    # query string e virou POST com o secret no corpo. As DUAS chamadas a
    # /oauth/access_token são POST agora, então uma rota só com side_effect
    # devolve as respostas na ordem em que o callback as consome.
    respx.post("https://graph.facebook.com/v22.0/oauth/access_token").mock(
        side_effect=[
            Response(200, json={"access_token": "short_xyz", "expires_in": 3600}),
            Response(200, json={"access_token": "long_60d", "expires_in": 5184000}),
        ]
    )
    respx.get("https://graph.facebook.com/v22.0/me").mock(
        return_value=Response(200, json={"id": "12345", "email": "ok@v4company.com", "name": "Ok"})
    )
    respx.get("https://graph.facebook.com/v22.0/debug_token").mock(
        return_value=Response(
            200,
            json={
                "data": {
                    "scopes": [
                        "ads_read",
                        "ads_management",
                        "business_management",
                        "email",
                        "public_profile",
                    ]
                }
            },
        )
    )
    respx.get("https://graph.facebook.com/v22.0/me/adaccounts").mock(
        return_value=Response(
            200,
            json={
                "data": [
                    {
                        "id": "act_111",
                        "name": "Cliente Alpha",
                        "account_status": 1,
                        "currency": "BRL",
                        "timezone_name": "America/Sao_Paulo",
                    }
                ]
            },
        )
    )

    resp = await client.get(
        f"/oauth/meta/callback?code=fake_code&state={state}",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/admin?meta_connected=1" in resp.headers["location"]

    # Verify persistence
    async with pool.acquire() as conn:
        oc = await meta_oauth_connections.get_active_for_manager(conn, mid)
        assert oc is not None
        assert oc.fb_email == "ok@v4company.com"
        assert "ads_read" in oc.scopes
        # Modelo B: callback deve NÃO auto-grant — zero rows em manager_meta_account_access.
        granted = await manager_meta_account_access.list_accounts_for_manager(conn, mid)
        assert granted == [], "Callback não deve auto-grant matrix access (Modelo B)"


@pytest.mark.integration
@respx.mock
async def test_oauth_callback_blocks_missing_essentials(client: AsyncClient) -> None:
    """debug_token returns scopes WITHOUT ads_read → 302 access-denied."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="ms@v4company.com", full_name="Ms")

    state = _make_state(str(mid))

    # F82: a troca short→long-lived deixou de ser GET com o `client_secret` na
    # query string e virou POST com o secret no corpo. As DUAS chamadas a
    # /oauth/access_token são POST agora, então uma rota só com side_effect
    # devolve as respostas na ordem em que o callback as consome.
    respx.post("https://graph.facebook.com/v22.0/oauth/access_token").mock(
        side_effect=[
            Response(200, json={"access_token": "short_xyz", "expires_in": 3600}),
            Response(200, json={"access_token": "long_60d", "expires_in": 5184000}),
        ]
    )
    respx.get("https://graph.facebook.com/v22.0/me").mock(
        return_value=Response(200, json={"id": "12345", "email": "ms@v4company.com", "name": "Ms"})
    )
    respx.get("https://graph.facebook.com/v22.0/debug_token").mock(
        return_value=Response(200, json={"data": {"scopes": ["ads_management", "email"]}})
    )

    resp = await client.get(
        f"/oauth/meta/callback?code=fake_code&state={state}",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "meta_scopes_missing" in resp.headers["location"]
    assert "ads_read" in resp.headers["location"]


@pytest.mark.integration
@respx.mock
async def test_oauth_callback_accepts_personal_fb_email(client: AsyncClient) -> None:
    """fb_email NÃO precisa ser @v4company.com — Facebook account é PESSOAL do gestor.

    Authoritative auth é o manager_id no state HMAC (assinado quando gestor já
    estava logado V4 em /admin). fb_email é metadata cosmético — armazenado em
    meta_oauth_connections.fb_email pra display, mas não usado pra auth check.

    Sprint M.2a fix: removido is_allowed_email(fb_email) check do callback Meta
    (era restrição impraticável — contas FB pessoais usam gmail/hotmail).
    """
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="dev@v4company.com", full_name="Dev")

    state = _make_state(str(mid))

    # F82: a troca short→long-lived deixou de ser GET com o `client_secret` na
    # query string e virou POST com o secret no corpo. As DUAS chamadas a
    # /oauth/access_token são POST agora, então uma rota só com side_effect
    # devolve as respostas na ordem em que o callback as consome.
    respx.post("https://graph.facebook.com/v22.0/oauth/access_token").mock(
        side_effect=[
            Response(200, json={"access_token": "short_xyz", "expires_in": 3600}),
            Response(200, json={"access_token": "long_60d", "expires_in": 5184000}),
        ]
    )
    respx.get("https://graph.facebook.com/v22.0/me").mock(
        return_value=Response(
            200,
            json={"id": "999", "email": "wellington.ribeiro.eng@gmail.com", "name": "Wellington"},
        )
    )
    respx.get("https://graph.facebook.com/v22.0/debug_token").mock(
        return_value=Response(
            200,
            json={
                "data": {
                    "scopes": [
                        "ads_read",
                        "ads_management",
                        "business_management",
                        "email",
                        "public_profile",
                    ]
                }
            },
        )
    )
    respx.get("https://graph.facebook.com/v22.0/me/adaccounts").mock(
        return_value=Response(200, json={"data": []})
    )

    resp = await client.get(
        f"/oauth/meta/callback?code=fake_code&state={state}",
        follow_redirects=False,
    )
    # NÃO deve mais bloquear por domain — deve completar OAuth flow
    assert resp.status_code == 302
    assert "/admin?meta_connected=1" in resp.headers["location"]
    assert "reason=domain" not in resp.headers["location"]


@pytest.mark.integration
async def test_oauth_callback_handles_error_param(client: AsyncClient) -> None:
    """Meta returned ?error=access_denied → 302 access-denied."""
    resp = await client.get(
        "/oauth/meta/callback?error=access_denied&error_description=user_cancelled",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "meta_oauth_error" in resp.headers["location"]
