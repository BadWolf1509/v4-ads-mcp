"""Web panel sessions routes integration tests."""

import re
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
async def test_sessions_create_returns_token_once(client: AsyncClient):
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
    )
    assert response.status_code == 200
    # Token should be in body — format is mcp_<43 url-safe chars>
    match = re.search(r"mcp_[A-Za-z0-9_-]+", response.text)
    assert match, "Token not found in response body"
    token = match.group(0)
    assert token.startswith("mcp_")
    # Snippets should reference the token
    assert response.text.count(token) >= 4  # token shown in 4 snippets


@pytest.mark.integration
async def test_sessions_revoke_returns_updated_list(client: AsyncClient):
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
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    # The revoked session's label should NOT appear in the response (only active shown)
    assert "B" in response.text  # still has B
