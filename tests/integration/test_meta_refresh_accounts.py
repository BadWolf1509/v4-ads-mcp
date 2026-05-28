"""Integration tests: /oauth/meta/refresh-accounts endpoint (Modelo B).

Modelo B: refresh-accounts uses shared system-user token from settings
(META_SYSTEM_USER_TOKEN), NOT the personal OAuth connection of the logged-in
manager. Grants are controlled exclusively by the admin access matrix — this
endpoint does NOT auto-grant any manager_meta_account_access rows.
"""

from uuid import uuid4

import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.db.repositories import managers, meta_ad_accounts

pytestmark = pytest.mark.asyncio

_SIGNING_KEY = "x" * 32
_AES_MASTER = "y" * 43
_SYSTEM_TOKEN = "fake_system_user_token"


@pytest.fixture
async def pg() -> PostgresContainer:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture
async def app_with_db(pg, monkeypatch):
    dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("SESSION_SIGNING_KEY", _SIGNING_KEY)
    monkeypatch.setenv("AES_MASTER_KEY", _AES_MASTER)
    monkeypatch.setenv("META_APP_ID", "test_app_id")
    monkeypatch.setenv("META_APP_SECRET", "test_app_secret")
    monkeypatch.setenv("META_SYSTEM_USER_TOKEN", _SYSTEM_TOKEN)

    from src.app import create_app

    app = create_app(skip_db_init=True)
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        await migrate.run_all()
        yield app
    finally:
        await connection.close_pool()


@pytest.fixture
async def client(app_with_db) -> AsyncClient:
    transport = ASGITransport(app=app_with_db)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _seed_manager():
    """Seed a bare manager (no Meta OAuth connection required in Modelo B)."""
    mid = uuid4()
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        await managers.create(conn, manager_id=mid, email="t@v4company.com", full_name="Tester")
    return mid


@pytest.mark.integration
@respx.mock
async def test_refresh_accounts_happy_path(app_with_db):
    """POST /refresh-accounts with system-user token → upsert meta_ad_accounts → redirect.

    No manager_meta_account_access rows must be created (grants are matrix-only).
    """
    mid = await _seed_manager()

    # Mock Graph /me/adaccounts (system user resolves /me to system user)
    respx.get("https://graph.facebook.com/v22.0/me/adaccounts").mock(
        return_value=Response(
            200,
            json={
                "data": [
                    {
                        "id": "act_777",
                        "name": "Refreshed Client",
                        "business": {"id": "bm_x", "name": "Refreshed BM"},
                        "account_status": 1,
                        "currency": "BRL",
                        "timezone_name": "America/Sao_Paulo",
                    }
                ]
            },
        )
    )

    from src.web.deps import CurrentUser, current_manager

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mgr = await managers.get_by_id(conn, mid)
    assert mgr is not None

    def _fake_current_manager():
        return CurrentUser(mgr)

    app_with_db.dependency_overrides[current_manager] = _fake_current_manager

    transport = ASGITransport(app=app_with_db)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post(
            "/oauth/meta/refresh-accounts",
            follow_redirects=False,
        )

    app_with_db.dependency_overrides.clear()

    assert resp.status_code == 302
    assert "/admin?meta_refreshed=1" in resp.headers["location"]

    # Verify upsert happened in meta_ad_accounts
    async with pool.acquire() as conn:
        account = await meta_ad_accounts.get_by_id(conn, "act_777")
    assert account is not None
    assert account.account_name == "Refreshed Client"

    # Verify NO auto-grant was created (Modelo B — matrix controls grants)
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM manager_meta_account_access WHERE manager_id = $1",
            mid,
        )
    assert count == 0, "refresh-accounts must NOT auto-grant any ad account access"


@pytest.mark.integration
async def test_refresh_accounts_no_system_token_returns_422(app_with_db, monkeypatch):
    """Empty META_SYSTEM_USER_TOKEN → 422 with PT-BR error message."""
    # Override env AFTER app fixture (get_settings() reads env fresh each call)
    monkeypatch.setenv("META_SYSTEM_USER_TOKEN", "")

    mid = await _seed_manager()

    from src.web.deps import CurrentUser, current_manager

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mgr = await managers.get_by_id(conn, mid)
    assert mgr is not None

    def _fake_current_manager():
        return CurrentUser(mgr)

    app_with_db.dependency_overrides[current_manager] = _fake_current_manager

    transport = ASGITransport(app=app_with_db)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post(
            "/oauth/meta/refresh-accounts",
            follow_redirects=False,
        )

    app_with_db.dependency_overrides.clear()

    assert resp.status_code == 422
    body = resp.text
    assert "system user" in body.lower() or "não configurado" in body.lower()
