"""Unit-style tests for SecurityHeadersMiddleware (no DB, no testcontainers).

Runs in check_pre_push.py (step 5/5 non-DB integration) alongside unit tests.
"""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.web.middleware import SecurityHeadersMiddleware


def _app() -> FastAPI:
    a = FastAPI()
    a.add_middleware(SecurityHeadersMiddleware)

    @a.get("/x")
    async def x() -> dict[str, bool]:
        return {"ok": True}

    return a


@pytest.mark.asyncio
async def test_security_headers_present() -> None:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/x")
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "referrer-policy" in r.headers
    assert "strict-transport-security" in r.headers
    # CSP is now enforced (validated against the full origin inventory + smoke).
    assert "content-security-policy" in r.headers
    assert "content-security-policy-report-only" not in r.headers  # no longer report-only


@pytest.mark.asyncio
async def test_security_headers_csp_value() -> None:
    """Enforced CSP must reference the known safe origins."""
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/x")
    csp = r.headers["content-security-policy"]
    assert "default-src" in csp
    assert "script-src" in csp
    assert "https://unpkg.com" in csp
    assert "https://fonts.bunny.net" in csp
    # 2026-08-11: o Tailwind saiu do CDN (CSS gerado offline em /static), o que
    # removeu a origem e o 'unsafe-eval' que o compilador em runtime exigia.
    assert "https://cdn.tailwindcss.com" not in csp
    assert "unsafe-eval" not in csp


@pytest.mark.asyncio
async def test_hsts_value() -> None:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/x")
    hsts = r.headers["strict-transport-security"]
    assert "max-age=" in hsts
    assert "includeSubDomains" in hsts


@pytest.mark.asyncio
async def test_referrer_policy_value() -> None:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/x")
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
