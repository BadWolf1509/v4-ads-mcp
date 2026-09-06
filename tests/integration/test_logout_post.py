"""Integration tests: logout-CSRF fix — POST /logout, GET /logout → 405."""

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
async def test_logout_get_returns_405(client: AsyncClient):
    """GET /logout must be rejected (405) now that only POST is allowed."""
    response = await client.get("/logout", follow_redirects=False)
    assert response.status_code == 405


@pytest.mark.integration
async def test_logout_post_same_origin_clears_cookie_and_redirects(client: AsyncClient):
    """POST /logout with matching origin header → 302 /login + clears session cookie."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(
            conn,
            manager_id=mid,
            email="logout_post@v4company.com",
            full_name=None,
        )

    cookie = sign_panel_session(
        manager_id=str(mid),
        email="logout_post@v4company.com",
        signing_key=_SIGNING_KEY,
        aud="panel",
    )
    # The CSRF middleware compares urlparse(origin).netloc to the Host header.
    # AsyncClient base_url="http://test" → Host: test; origin must match.
    response = await client.post(
        "/logout",
        cookies={PANEL_SESSION_COOKIE_NAME: cookie},
        follow_redirects=False,
        headers={"origin": "http://test"},
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/login"
    # Session cookie must be cleared
    set_cookie = response.headers.get("set-cookie", "")
    assert PANEL_SESSION_COOKIE_NAME in set_cookie
