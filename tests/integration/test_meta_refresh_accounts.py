"""Integration tests Sprint M.2b: /oauth/meta/refresh-accounts endpoint."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.db.repositories import managers, meta_ad_accounts, meta_oauth_connections

pytestmark = pytest.mark.asyncio

_SIGNING_KEY = "x" * 32
_AES_MASTER = "y" * 43


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


async def _seed_manager_with_meta(*, token_expires_days: int = 60):
    """Seed manager + meta_oauth_connections with real-ish encrypted token."""
    from src.auth.tokens import derive_master_key_from_settings, encrypt_refresh_token
    from src.config import get_settings

    mid = uuid4()
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        await managers.create(conn, manager_id=mid, email="t@v4company.com", full_name="Tester")
        settings = get_settings()
        master_key = derive_master_key_from_settings(settings.aes_master_key)
        real_enc = encrypt_refresh_token("fake_long_token", master_key)
        await meta_oauth_connections.upsert(
            conn,
            manager_id=mid,
            fb_user_id="fb_user_test",
            fb_email="t@v4company.com",
            access_token_enc=real_enc,
            token_expires_at=datetime.now(UTC) + timedelta(days=token_expires_days),
            scopes=["ads_read", "ads_management"],
        )
    return mid


@pytest.mark.integration
@respx.mock
async def test_refresh_accounts_happy_path(app_with_db, monkeypatch):
    """POST /refresh-accounts → respx Graph /me/adaccounts → upsert + grant + redirect."""
    mid = await _seed_manager_with_meta()

    # Mock Graph /me/adaccounts
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

    # Override current_manager dependency to bypass session cookie auth
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

    # Verify upsert happened
    async with pool.acquire() as conn:
        account = await meta_ad_accounts.get_by_id(conn, "act_777")
    assert account is not None
    assert account.account_name == "Refreshed Client"


@pytest.mark.integration
async def test_refresh_accounts_token_expired_returns_422(app_with_db):
    """token_expires_at no passado → 422 PT-BR error."""
    mid = await _seed_manager_with_meta(token_expires_days=-1)

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
    assert "expirou" in body.lower()
