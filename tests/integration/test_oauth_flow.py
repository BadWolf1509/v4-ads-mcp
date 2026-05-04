"""Integration tests for the OAuth flow with respx mocks."""

from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response
from testcontainers.postgres import PostgresContainer

from src.auth.oauth_state import sign_state
from src.db import connection, migrate
from src.db.repositories import google_oauth_connections, managers

_SIGNING_KEY = "x" * 32
_AES_MASTER = "y" * 43  # urlsafe base64 source for 32 bytes


@pytest.fixture
async def pg() -> PostgresContainer:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture
async def app_with_db(pg, monkeypatch):
    """App with real DB pool initialized."""
    dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("SESSION_SIGNING_KEY", _SIGNING_KEY)
    monkeypatch.setenv("AES_MASTER_KEY", _AES_MASTER)

    from src.app import create_app  # lazy import to avoid module-level create_app() triggering

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


@pytest.mark.integration
async def test_start_redirects_to_google(client: AsyncClient) -> None:
    # Bootstrap a manager.
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="boot@v4.com", full_name="Boot")
    invite = sign_state({"manager_id": str(mid)}, _SIGNING_KEY)

    response = await client.get(f"/oauth/google/start?invite={invite}", follow_redirects=False)
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    qs = parse_qs(urlparse(location).query)
    assert "adwords" in qs["scope"][0]
    assert qs["access_type"] == ["offline"]
    assert qs["prompt"] == ["consent"]


@pytest.mark.integration
async def test_start_rejects_invalid_invite(client: AsyncClient) -> None:
    response = await client.get("/oauth/google/start?invite=bogus", follow_redirects=False)
    assert response.status_code == 400


@pytest.mark.integration
@respx.mock
async def test_callback_persists_encrypted_refresh_token(client: AsyncClient) -> None:
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="cb@v4.com", full_name=None)

    state = sign_state({"manager_id": str(mid)}, _SIGNING_KEY)

    # Mock Google's token + userinfo endpoints.
    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=Response(
            200,
            json={
                "access_token": "ya29.fake",
                "refresh_token": "1//06fake-refresh",
                "expires_in": 3600,
                "scope": "https://www.googleapis.com/auth/adwords",
                "token_type": "Bearer",
            },
        )
    )
    respx.get("https://www.googleapis.com/oauth2/v2/userinfo").mock(
        return_value=Response(200, json={"email": "manager@gmail.com"})
    )

    response = await client.get(
        f"/oauth/google/callback?code=fake-code&state={state}",
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "Conectado" in response.text

    # Verify the connection was persisted with encrypted refresh token.
    async with pool.acquire() as conn:
        c = await google_oauth_connections.get_active_for_manager(conn, mid)
    assert c is not None
    assert c.google_email == "manager@gmail.com"
    assert c.refresh_token_enc != b"1//06fake-refresh"  # encrypted, not plaintext
    assert len(c.refresh_token_enc) > 16  # nonce + ct + tag


@pytest.mark.integration
async def test_callback_rejects_missing_refresh_token(client: AsyncClient) -> None:
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="nr@v4.com", full_name=None)
    state = sign_state({"manager_id": str(mid)}, _SIGNING_KEY)

    with respx.mock:
        respx.post("https://oauth2.googleapis.com/token").mock(
            return_value=Response(200, json={"access_token": "x"})  # no refresh_token
        )
        response = await client.get(
            f"/oauth/google/callback?code=fake&state={state}",
            follow_redirects=False,
        )
    assert response.status_code == 400
    assert "refresh_token" in response.text


@pytest.mark.integration
async def test_callback_rejects_google_error(client: AsyncClient) -> None:
    response = await client.get(
        "/oauth/google/callback?error=access_denied",
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "access_denied" in response.text
