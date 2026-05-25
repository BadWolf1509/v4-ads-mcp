"""Integration tests for Meta OAuth callback flow via respx (Sprint M.2a Task 8)."""

from uuid import uuid4

import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response
from testcontainers.postgres import PostgresContainer

from src.auth.oauth_state import sign_state
from src.db import connection, migrate
from src.db.repositories import managers, meta_oauth_connections

_SIGNING_KEY = "x" * 32
_AES_MASTER = "y" * 43  # urlsafe base64 source for 32 bytes


@pytest.fixture
async def pg() -> PostgresContainer:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture
async def app_with_db(pg, monkeypatch):
    """App with real DB pool initialized and required settings injected."""
    dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("SESSION_SIGNING_KEY", _SIGNING_KEY)
    monkeypatch.setenv("AES_MASTER_KEY", _AES_MASTER)
    monkeypatch.setenv("META_APP_ID", "test_app_id")
    monkeypatch.setenv("META_APP_SECRET", "test_app_secret")

    from src.app import create_app  # lazy import avoids module-level create_app() triggering

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


def _make_state(manager_id: str) -> str:
    return sign_state(
        {"manager_id": manager_id, "aud": "meta_oauth"},
        _SIGNING_KEY,
    )


@pytest.mark.integration
@respx.mock
async def test_oauth_callback_happy_path(client: AsyncClient) -> None:
    """Full happy path: short token → long token → /me → debug_token → /me/adaccounts."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="ok@v4company.com", full_name="Ok")

    state = _make_state(str(mid))

    respx.post("https://graph.facebook.com/v22.0/oauth/access_token").mock(
        return_value=Response(200, json={"access_token": "short_xyz", "expires_in": 3600})
    )
    respx.get("https://graph.facebook.com/v22.0/oauth/access_token").mock(
        return_value=Response(200, json={"access_token": "long_60d", "expires_in": 5184000})
    )
    respx.get("https://graph.facebook.com/v22.0/me").mock(
        return_value=Response(200, json={"id": "12345", "email": "ok@v4company.com", "name": "Ok"})
    )
    respx.get("https://graph.facebook.com/v22.0/debug_token").mock(
        return_value=Response(
            200,
            json={
                "data": {
                    "scopes": [
                        "ads_read",
                        "ads_management",
                        "business_management",
                        "email",
                        "public_profile",
                    ]
                }
            },
        )
    )
    respx.get("https://graph.facebook.com/v22.0/me/adaccounts").mock(
        return_value=Response(
            200,
            json={
                "data": [
                    {
                        "id": "act_111",
                        "name": "Cliente Alpha",
                        "account_status": 1,
                        "currency": "BRL",
                        "timezone_name": "America/Sao_Paulo",
                    }
                ]
            },
        )
    )

    resp = await client.get(
        f"/oauth/meta/callback?code=fake_code&state={state}",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/admin?meta_connected=1" in resp.headers["location"]

    # Verify persistence
    async with pool.acquire() as conn:
        oc = await meta_oauth_connections.get_active_for_manager(conn, mid)
        assert oc is not None
        assert oc.fb_email == "ok@v4company.com"
        assert "ads_read" in oc.scopes


@pytest.mark.integration
@respx.mock
async def test_oauth_callback_blocks_missing_essentials(client: AsyncClient) -> None:
    """debug_token returns scopes WITHOUT ads_read → 302 access-denied."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="ms@v4company.com", full_name="Ms")

    state = _make_state(str(mid))

    respx.post("https://graph.facebook.com/v22.0/oauth/access_token").mock(
        return_value=Response(200, json={"access_token": "short_xyz", "expires_in": 3600})
    )
    respx.get("https://graph.facebook.com/v22.0/oauth/access_token").mock(
        return_value=Response(200, json={"access_token": "long_60d", "expires_in": 5184000})
    )
    respx.get("https://graph.facebook.com/v22.0/me").mock(
        return_value=Response(200, json={"id": "12345", "email": "ms@v4company.com", "name": "Ms"})
    )
    respx.get("https://graph.facebook.com/v22.0/debug_token").mock(
        return_value=Response(200, json={"data": {"scopes": ["ads_management", "email"]}})
    )

    resp = await client.get(
        f"/oauth/meta/callback?code=fake_code&state={state}",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "meta_scopes_missing" in resp.headers["location"]
    assert "ads_read" in resp.headers["location"]


@pytest.mark.integration
@respx.mock
async def test_oauth_callback_blocks_non_v4_email(client: AsyncClient) -> None:
    """/me returns email outside @v4company.com → 302 access-denied (domain)."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="nv@v4company.com", full_name="Nv")

    state = _make_state(str(mid))

    respx.post("https://graph.facebook.com/v22.0/oauth/access_token").mock(
        return_value=Response(200, json={"access_token": "short_xyz", "expires_in": 3600})
    )
    respx.get("https://graph.facebook.com/v22.0/oauth/access_token").mock(
        return_value=Response(200, json={"access_token": "long_60d", "expires_in": 5184000})
    )
    respx.get("https://graph.facebook.com/v22.0/me").mock(
        return_value=Response(
            200, json={"id": "999", "email": "stranger@external.com", "name": "X"}
        )
    )

    resp = await client.get(
        f"/oauth/meta/callback?code=fake_code&state={state}",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "reason=domain" in resp.headers["location"]


@pytest.mark.integration
async def test_oauth_callback_handles_error_param(client: AsyncClient) -> None:
    """Meta returned ?error=access_denied → 302 access-denied."""
    resp = await client.get(
        "/oauth/meta/callback?error=access_denied&error_description=user_cancelled",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "meta_oauth_error" in resp.headers["location"]
