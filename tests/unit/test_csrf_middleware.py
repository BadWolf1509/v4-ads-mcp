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

    @a.post("/oauth/meta/revoke")
    async def meta_revoke() -> dict[str, bool]:
        return {"ok": True}

    @a.post("/oauth/meta/refresh-accounts")
    async def meta_refresh() -> dict[str, bool]:
        return {"ok": True}

    @a.post("/oauth/meta/data-deletion-callback")
    async def meta_data_deletion() -> dict[str, bool]:
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
async def test_csrf_nao_isenta_o_prefixo_oauth_inteiro() -> None:
    """A isencao e por ROTA, nao por prefixo.

    Os endpoints OAuth de verdade sao GET (start/callback) — metodo seguro,
    nunca checado. Isentar `/oauth/` inteiro so servia pra deixar POST de
    cookie de fora da checagem.
    """
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://testserver") as c:
        r = await c.post(
            "/oauth/callback", headers={"origin": "http://evil.com", "host": "testserver"}
        )
        assert r.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("rota", ["/oauth/meta/revoke", "/oauth/meta/refresh-accounts"])
async def test_mutacao_do_painel_sob_oauth_nao_e_isenta(rota: str) -> None:
    """revoke e refresh-accounts sao acoes do PAINEL autenticadas por cookie.

    Vivem sob /oauth por acidente de roteamento (o APIRouter tem prefix
    /oauth/meta), nao porque precisem da isencao. Origin divergente tem que
    bater no 403 como qualquer outro POST de cookie.
    """
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://testserver") as c:
        r = await c.post(rota, headers={"origin": "http://evil.com", "host": "testserver"})
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_callback_de_data_deletion_segue_isento() -> None:
    """Unico POST sob /oauth que precisa da isencao: server-to-server da Meta,
    com HMAC proprio no signed_request."""
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://testserver") as c:
        r = await c.post(
            "/oauth/meta/data-deletion-callback",
            headers={"origin": "https://facebook.com", "host": "testserver"},
        )
        assert r.status_code == 200
