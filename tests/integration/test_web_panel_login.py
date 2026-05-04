"""Web panel login + dashboard integration tests."""

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from testcontainers.postgres import PostgresContainer

from src.auth.panel_session import (
    PANEL_SESSION_COOKIE_NAME,
    sign_panel_session,
)
from src.db import connection, migrate
from src.db.repositories import managers

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

    from src.app import (
        create_app,  # lazy import to avoid module-level create_app() before env is set
    )

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
async def test_unauthenticated_dashboard_redirects_to_login(client: AsyncClient):
    response = await client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


@pytest.mark.integration
async def test_login_page_renders(client: AsyncClient):
    response = await client.get("/login")
    assert response.status_code == 200
    assert "Entrar com Google V4" in response.text
    assert "@v4company.com" in response.text


@pytest.mark.integration
async def test_authenticated_dashboard_renders(client: AsyncClient):
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(
            conn, manager_id=mid, email="x@v4company.com", full_name="X", role="admin"
        )

    cookie = sign_panel_session(
        manager_id=str(mid),
        email="x@v4company.com",
        signing_key=_SIGNING_KEY,
    )
    response = await client.get("/", cookies={PANEL_SESSION_COOKIE_NAME: cookie})
    assert response.status_code == 200
    assert "x@v4company.com" in response.text
    assert "Bem-vindo" in response.text


@pytest.mark.integration
async def test_logout_clears_cookie(client: AsyncClient):
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="lo@v4company.com", full_name=None)

    cookie = sign_panel_session(
        manager_id=str(mid),
        email="lo@v4company.com",
        signing_key=_SIGNING_KEY,
    )
    response = await client.get(
        "/logout",
        cookies={PANEL_SESSION_COOKIE_NAME: cookie},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/login"
    # Cookie should be cleared (max-age=0 or set to deleted)
    set_cookie = response.headers.get("set-cookie", "")
    assert PANEL_SESSION_COOKIE_NAME in set_cookie


@pytest.mark.integration
async def test_dashboard_redirects_logged_in_user_from_login(client: AsyncClient):
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="lo2@v4company.com", full_name=None)

    cookie = sign_panel_session(
        manager_id=str(mid),
        email="lo2@v4company.com",
        signing_key=_SIGNING_KEY,
    )
    response = await client.get(
        "/login",
        cookies={PANEL_SESSION_COOKIE_NAME: cookie},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/"


@pytest.mark.integration
async def test_invalid_cookie_redirects_to_login(client: AsyncClient):
    response = await client.get(
        "/",
        cookies={PANEL_SESSION_COOKIE_NAME: "garbage"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/login"
