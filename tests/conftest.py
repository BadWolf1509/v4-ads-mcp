"""Shared pytest fixtures.

Most tests should consume `app` and `client` from here. The DB-backed
integration tests use the `pg` fixture (from individual test files)
because not every test needs a Postgres container.
"""

import os
import sys
from collections.abc import AsyncGenerator, Generator
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

# Provide a complete env so `Settings()` validates everywhere.
_TEST_ENV = {
    "APP_ENV": "development",
    "DATABASE_URL": "postgresql://postgres:postgres@localhost:5432/test",
    "SESSION_SIGNING_KEY": "x" * 32,
    "AES_MASTER_KEY": "y" * 32,
    "GOOGLE_OAUTH_CLIENT_ID": "test-client.apps.googleusercontent.com",
    "GOOGLE_OAUTH_CLIENT_SECRET": "test-secret",
    "GOOGLE_ADS_DEVELOPER_TOKEN": "test-dev-token",
    "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "1234567890",
    "SUPABASE_URL": "https://test.supabase.co",
    "SUPABASE_ANON_KEY": "test-anon",
    "SUPABASE_SERVICE_KEY": "test-service",
    "LOG_LEVEL": "warning",
    "META_APP_ID": "test_meta_app_123456789",
    "META_APP_SECRET": "test_meta_secret_dummy_value_at_least_32_chars_long",
}

# Testcontainers needs DOCKER_HOST + Ryuk-disable on Windows + Docker Desktop
# (Ryuk's image pull intermittently 404s on this combo). On Linux CI the
# Docker socket is auto-detected, so don't override.
_IS_WINDOWS = sys.platform == "win32"
_TESTCONTAINERS_DEFAULTS = (
    {
        "DOCKER_HOST": os.environ.get("DOCKER_HOST", "npipe:////./pipe/docker_engine"),
        "TESTCONTAINERS_RYUK_DISABLED": os.environ.get("TESTCONTAINERS_RYUK_DISABLED", "true"),
    }
    if _IS_WINDOWS
    else {}
)


@pytest.fixture(autouse=True)
def _test_env() -> Generator[None, None, None]:
    """Inject test env over real env. Settings reads only what we provide here; testcontainers/Docker SDK keeps access to Windows env (LOCALAPPDATA, etc) needed for container management."""
    with patch.dict(os.environ, {**_TEST_ENV, **_TESTCONTAINERS_DEFAULTS}, clear=False):
        yield


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client bound to the FastAPI app (no real DB)."""
    from src.app import create_app

    app = create_app(skip_db_init=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
