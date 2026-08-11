"""Web panel login + dashboard integration tests."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.auth.panel_session import (
    PANEL_SESSION_COOKIE_NAME,
    sign_panel_session,
)
from src.db import connection
from src.db.repositories import managers

_SIGNING_KEY = "x" * 32


@pytest.mark.integration
async def test_unauthenticated_dashboard_redirects_to_login(client: AsyncClient):
    response = await client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


@pytest.mark.integration
async def test_login_page_renders(client: AsyncClient):
    response = await client.get("/login")
    assert response.status_code == 200
    assert "Entrar com Google V4" in response.text
    assert "@v4company.com" in response.text


@pytest.mark.integration
async def test_login_nao_renderiza_hamburguer_nem_drawer(client: AsyncClient):
    """Deslogado nao existe navegacao — o botao abria uma gaveta vazia e travava o scroll."""
    response = await client.get("/login")
    assert response.status_code == 200
    assert "v4-header__hamburger" not in response.text
    assert 'id="mobile-drawer"' not in response.text


@pytest.mark.integration
async def test_authenticated_dashboard_renders(client: AsyncClient):
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(
            conn, manager_id=mid, email="x@v4company.com", full_name="X", role="admin"
        )

    cookie = sign_panel_session(
        manager_id=str(mid),
        email="x@v4company.com",
        signing_key=_SIGNING_KEY,
    )
    response = await client.get("/", cookies={PANEL_SESSION_COOKIE_NAME: cookie})
    assert response.status_code == 200
    assert "x@v4company.com" in response.text
    assert "Bem-vindo" in response.text


@pytest.mark.integration
async def test_logout_clears_cookie(client: AsyncClient):
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="lo@v4company.com", full_name=None)

    cookie = sign_panel_session(
        manager_id=str(mid),
        email="lo@v4company.com",
        signing_key=_SIGNING_KEY,
    )
    response = await client.post(
        "/logout",
        cookies={PANEL_SESSION_COOKIE_NAME: cookie},
        follow_redirects=False,
        headers={"origin": "http://test"},
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/login"
    # Cookie should be cleared (max-age=0 or set to deleted)
    set_cookie = response.headers.get("set-cookie", "")
    assert PANEL_SESSION_COOKIE_NAME in set_cookie


@pytest.mark.integration
async def test_dashboard_redirects_logged_in_user_from_login(client: AsyncClient):
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="lo2@v4company.com", full_name=None)

    cookie = sign_panel_session(
        manager_id=str(mid),
        email="lo2@v4company.com",
        signing_key=_SIGNING_KEY,
    )
    response = await client.get(
        "/login",
        cookies={PANEL_SESSION_COOKIE_NAME: cookie},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/"


@pytest.mark.integration
async def test_invalid_cookie_redirects_to_login(client: AsyncClient):
    response = await client.get(
        "/",
        cookies={PANEL_SESSION_COOKIE_NAME: "garbage"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


@pytest.mark.integration
async def test_access_denied_meta_state_invalid_shows_friendly_message(client: AsyncClient):
    """B3: internal meta OAuth error codes must NOT be shown raw; friendly PT-BR message instead."""
    response = await client.get("/access-denied?reason=meta_state_invalid")
    assert response.status_code == 200
    assert "Reason:" not in response.text
    assert "Ocorreu um erro inesperado durante a autenticação" in response.text
    # Raw reason is preserved in an HTML comment for debugging, not in visible content.
    assert "<!-- reason: meta_state_invalid -->" in response.text
