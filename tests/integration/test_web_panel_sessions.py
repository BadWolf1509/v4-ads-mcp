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
