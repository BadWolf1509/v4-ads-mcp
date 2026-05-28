"""Integration tests: invalid UUID in path params returns 404 (not 500).

Covers:
  - GET /sessions/not-a-uuid              → 404  (was: 500 from bare UUID())
  - GET /admin/access/not-a-uuid          → 404  (Google manager detail; admin auth)
  - GET /legal/data-deletion-status/not-a-uuid → 422 (FastAPI path-type validation)
"""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.auth.panel_session import PANEL_SESSION_COOKIE_NAME, sign_panel_session
from src.db import connection
from src.db.repositories import managers

_SIGNING_KEY = "x" * 32


async def _create_manager(conn, *, email: str, role: str = "gestor") -> uuid4:
    mid = uuid4()
    await managers.create(conn, manager_id=mid, email=email, full_name=None, role=role)
    return mid


@pytest.mark.integration
async def test_session_detail_invalid_uuid_returns_404(client: AsyncClient) -> None:
    """GET /sessions/not-a-uuid with valid auth → 404, not 500."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = await _create_manager(conn, email="uuid-guard-sess@v4company.com")

    cookie = sign_panel_session(
        manager_id=str(mid),
        email="uuid-guard-sess@v4company.com",
        signing_key=_SIGNING_KEY,
    )
    response = await client.get(
        "/sessions/not-a-uuid",
        cookies={PANEL_SESSION_COOKIE_NAME: cookie},
        follow_redirects=False,
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_admin_access_manager_detail_invalid_uuid_returns_404(client: AsyncClient) -> None:
    """GET /admin/access/not-a-uuid with admin auth → 404, not 500."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        admin_id = await _create_manager(conn, email="uuid-guard-admin@v4company.com", role="admin")

    cookie = sign_panel_session(
        manager_id=str(admin_id),
        email="uuid-guard-admin@v4company.com",
        signing_key=_SIGNING_KEY,
    )
    response = await client.get(
        "/admin/access/not-a-uuid",
        cookies={PANEL_SESSION_COOKIE_NAME: cookie},
        follow_redirects=False,
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_data_deletion_status_invalid_uuid_returns_422(client: AsyncClient) -> None:
    """GET /legal/data-deletion-status/not-a-uuid → 422 (FastAPI path-type validation).

    Route signature is `code: UUID` so FastAPI validates before the handler runs.
    No auth needed — route is public.
    """
    response = await client.get(
        "/legal/data-deletion-status/not-a-uuid",
        follow_redirects=False,
    )
    assert response.status_code == 422
