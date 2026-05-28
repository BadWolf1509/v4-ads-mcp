"""Unit-style tests for CSRFOriginMiddleware (no DB, no testcontainers).

Runs in check_pre_push.py (step 5/5 non-DB integration) alongside unit tests.
"""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.web.middleware import CSRFOriginMiddleware


def _app() -> FastAPI:
    a = FastAPI()
    a.add_middleware(CSRFOriginMiddleware)

    @a.post("/x")
    async def x() -> dict[str, bool]:
        return {"ok": True}

    @a.get("/x")
    async def gx() -> dict[str, bool]:
        return {"ok": True}

    @a.post("/mcp")
    async def mcp() -> dict[str, bool]:
        return {"ok": True}

    @a.post("/oauth/callback")
    async def oauth_callback() -> dict[str, bool]:
        return {"ok": True}

    return a


@pytest.mark.asyncio
async def test_csrf_blocks_cross_origin_post() -> None:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://testserver") as c:
        r = await c.post("/x", headers={"origin": "http://evil.com", "host": "testserver"})
        assert r.status_code == 403
        assert "CSRF" in r.json()["detail"]


@pytest.mark.asyncio
async def test_csrf_allows_missing_origin_post() -> None:
    """POST with no Origin and no Referer is allowed (not a CSRF signal).

    Browsers always attach Origin to cross-site POSTs, so absence means a
    non-browser client (curl, server-to-server, tests). SameSite=Lax already
    blocks the session cookie on genuine cross-site POSTs; blocking absent-Origin
    here would add no protection while breaking legitimate non-browser callers.
    """
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://testserver") as c:
        r = await c.post("/x", headers={"host": "testserver"})
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_csrf_allows_same_origin_post() -> None:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://testserver") as c:
        r = await c.post("/x", headers={"origin": "http://testserver", "host": "testserver"})
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_csrf_allows_same_origin_referer() -> None:
    """Referer is accepted when Origin is absent (legacy browser pattern)."""
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://testserver") as c:
        r = await c.post(
            "/x",
            headers={"referer": "http://testserver/some/page", "host": "testserver"},
        )
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_csrf_allows_get() -> None:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://testserver") as c:
        assert (await c.get("/x", headers={"host": "testserver"})).status_code == 200


@pytest.mark.asyncio
async def test_csrf_exempts_mcp() -> None:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://testserver") as c:
        r = await c.post("/mcp", headers={"origin": "http://evil.com", "host": "testserver"})
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_csrf_exempts_oauth_prefix() -> None:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://testserver") as c:
        r = await c.post(
            "/oauth/callback", headers={"origin": "http://evil.com", "host": "testserver"}
        )
        assert r.status_code == 200
