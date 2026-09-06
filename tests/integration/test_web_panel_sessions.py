"""Web panel sessions routes integration tests."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.auth.panel_session import (
    PANEL_SESSION_COOKIE_NAME,
    sign_panel_session,
)
from src.auth.sessions import generate_session_token, hash_session_token
from src.db import connection
from src.db.repositories import managers, mcp_sessions

_SIGNING_KEY = "x" * 32


@pytest.mark.integration
async def test_sessions_list_requires_auth(client: AsyncClient):
    response = await client.get("/sessions", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


@pytest.mark.integration
async def test_drawer_marca_pagina_atual(client: AsyncClient):
    """No mobile o unico indicador de 'onde estou' e o aria-current do drawer."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="nav@v4company.com", full_name=None)

    cookie = sign_panel_session(
        manager_id=str(mid),
        email="nav@v4company.com",
        signing_key=_SIGNING_KEY,
        aud="panel",
    )
    response = await client.get("/sessions", cookies={PANEL_SESSION_COOKIE_NAME: cookie})
    assert response.status_code == 200
    drawer = response.text.split('id="mobile-drawer"', 1)[1]
    assert '<a href="/sessions" class="v4-drawer__link" aria-current="page">' in drawer


@pytest.mark.integration
async def test_sessions_create_redirects_to_detail(client: AsyncClient):
    """Task 5.2: POST /sessions/new now redirects to /sessions/{id}?token_flash=true.
    The plaintext token is no longer in the response body; it goes in a flash cookie."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="cs@v4company.com", full_name=None)

    cookie = sign_panel_session(
        manager_id=str(mid),
        email="cs@v4company.com",
        signing_key=_SIGNING_KEY,
        aud="panel",
    )
    response = await client.post(
        "/sessions/new",
        data={"label": "Test client", "ttl_days": "90"},
        cookies={PANEL_SESSION_COOKIE_NAME: cookie},
        follow_redirects=False,
    )
    # New flow: 303 redirect to /sessions/{id}?token_flash=true
    assert response.status_code == 303
    location = response.headers["location"]
    assert "token_flash=true" in location
    # Flash token cookie set for the detail page scope
    assert "v4_session_flash_token" in response.cookies


@pytest.mark.integration
async def test_sessions_revoke_list_page_returns_fragment(client: AsyncClient):
    """Revoke from the list page (HX-Current-URL=/sessions) → 200 + table fragment in-place."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="rv@v4company.com", full_name=None)
        token1 = generate_session_token()
        sess1 = await mcp_sessions.create(
            conn, manager_id=mid, token_hash=hash_session_token(token1), label="A"
        )
        token2 = generate_session_token()
        _sess2 = await mcp_sessions.create(
            conn, manager_id=mid, token_hash=hash_session_token(token2), label="B"
        )

    cookie = sign_panel_session(
        manager_id=str(mid),
        email="rv@v4company.com",
        signing_key=_SIGNING_KEY,
        aud="panel",
    )
    response = await client.post(
        f"/sessions/{sess1.id}/revoke",
        cookies={PANEL_SESSION_COOKIE_NAME: cookie},
        headers={
            "HX-Request": "true",
            "HX-Current-URL": "http://test/sessions",
        },
    )
    assert response.status_code == 200
    # Returns the table fragment — revoked session gone, other still present
    assert "B" in response.text  # still has B
    assert "sessions-table" in response.text  # it's the fragment, not the full page


@pytest.mark.integration
async def test_sessions_revoke_detail_page_returns_hx_redirect(client: AsyncClient):
    """Revoke from the detail page (HX-Current-URL=/sessions/<id>) → 204 + HX-Redirect header."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="rvd@v4company.com", full_name=None)
        token1 = generate_session_token()
        sess1 = await mcp_sessions.create(
            conn, manager_id=mid, token_hash=hash_session_token(token1), label="C"
        )

    cookie = sign_panel_session(
        manager_id=str(mid),
        email="rvd@v4company.com",
        signing_key=_SIGNING_KEY,
        aud="panel",
    )
    response = await client.post(
        f"/sessions/{sess1.id}/revoke",
        cookies={PANEL_SESSION_COOKIE_NAME: cookie},
        headers={
            "HX-Request": "true",
            "HX-Current-URL": f"http://test/sessions/{sess1.id}",
        },
    )
    assert response.status_code == 204
    assert response.headers.get("HX-Redirect") == "/sessions"


@pytest.mark.integration
async def test_sessions_list_include_revoked_shows_revoked(client: AsyncClient):
    """GET /sessions?include_revoked=1 includes a revoked session in the response."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="ir@v4company.com", full_name=None)
        token1 = generate_session_token()
        sess1 = await mcp_sessions.create(
            conn, manager_id=mid, token_hash=hash_session_token(token1), label="Revogada"
        )
        await mcp_sessions.revoke(conn, sess1.id)

    cookie = sign_panel_session(
        manager_id=str(mid),
        email="ir@v4company.com",
        signing_key=_SIGNING_KEY,
        aud="panel",
    )
    response = await client.get(
        "/sessions?include_revoked=1",
        cookies={PANEL_SESSION_COOKIE_NAME: cookie},
    )
    assert response.status_code == 200
    assert "Revogada" in response.text


@pytest.mark.integration
async def test_sessions_revoke_with_include_revoked_preserves_context(client: AsyncClient):
    """Revoke from list page with ?include_revoked=1 → fragment still shows revoked rows."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="rvir@v4company.com", full_name=None)
        # Active session — will be revoked
        token1 = generate_session_token()
        sess1 = await mcp_sessions.create(
            conn, manager_id=mid, token_hash=hash_session_token(token1), label="ToRevoke"
        )
        # Already-revoked session — must appear in the returned fragment
        token2 = generate_session_token()
        sess2 = await mcp_sessions.create(
            conn, manager_id=mid, token_hash=hash_session_token(token2), label="AlreadyRevoked"
        )
        await mcp_sessions.revoke(conn, sess2.id)

    cookie = sign_panel_session(
        manager_id=str(mid),
        email="rvir@v4company.com",
        signing_key=_SIGNING_KEY,
        aud="panel",
    )
    response = await client.post(
        f"/sessions/{sess1.id}/revoke",
        cookies={PANEL_SESSION_COOKIE_NAME: cookie},
        headers={
            "HX-Request": "true",
            "HX-Current-URL": "http://test/sessions?include_revoked=1",
        },
    )
    assert response.status_code == 200
    # Fragment must include the previously-revoked session (context preserved)
    assert "AlreadyRevoked" in response.text
    # The card title must reflect the all-sessions mode (no "não revogadas" text)
    assert "não revogadas" not in response.text
    assert "sessions-table" in response.text


@pytest.mark.integration
async def test_sessions_revoke_list_page_has_hx_trigger_toast(client: AsyncClient):
    """Revoke from the list page → HX-Trigger header contains 'toast'."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="rth@v4company.com", full_name=None)
        token1 = generate_session_token()
        sess1 = await mcp_sessions.create(
            conn, manager_id=mid, token_hash=hash_session_token(token1), label="ToastTest"
        )

    cookie = sign_panel_session(
        manager_id=str(mid),
        email="rth@v4company.com",
        signing_key=_SIGNING_KEY,
        aud="panel",
    )
    response = await client.post(
        f"/sessions/{sess1.id}/revoke",
        cookies={PANEL_SESSION_COOKIE_NAME: cookie},
        headers={
            "HX-Request": "true",
            "HX-Current-URL": "http://test/sessions",
        },
    )
    assert response.status_code == 200
    hx_trigger = response.headers.get("HX-Trigger", "")
    assert "toast" in hx_trigger


@pytest.mark.integration
async def test_sessions_revoke_sem_htmx_redireciona(client: AsyncClient):
    """Sem HTMX o POST tem que virar 303 pra /sessions (POST-redirect-GET).

    Renderizava a lista com 200: recarregar a pagina re-executava a acao. Os
    dois testes vizinhos so cobriam os ramos HTMX, e foi por isso que passou.
    """
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="rvn@v4company.com", full_name=None)
        token = generate_session_token()
        sess = await mcp_sessions.create(
            conn, manager_id=mid, token_hash=hash_session_token(token), label="D"
        )

    cookie = sign_panel_session(
        manager_id=str(mid),
        email="rvn@v4company.com",
        signing_key=_SIGNING_KEY,
        aud="panel",
    )
    response = await client.post(
        f"/sessions/{sess.id}/revoke",
        cookies={PANEL_SESSION_COOKIE_NAME: cookie},
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/sessions"
