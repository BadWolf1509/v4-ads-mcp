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
        aud="panel",
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
        aud="panel",
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


_POSTS_ADMIN_ACCESS_COM_MANAGER_ID = [
    ("/admin/access/toggle", {"customer_id": "1234567890", "desejado": "grant"}),
    ("/admin/access/meta/toggle", {"ad_account_id": "act_1", "desejado": "grant"}),
    ("/admin/access/bulk-grant", {"customer_ids": ["1234567890"]}),
    ("/admin/access/meta/bulk-grant", {"ad_account_ids": ["act_1"]}),
]


@pytest.mark.integration
@pytest.mark.parametrize(("url", "extra"), _POSTS_ADMIN_ACCESS_COM_MANAGER_ID)
async def test_post_com_manager_id_malformado_da_422(
    client: AsyncClient, url: str, extra: dict
) -> None:
    """`manager_id` malformado e erro de validacao (422), nao ValueError/500."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        admin_id = await _create_manager(conn, email="uuid-guard-post@v4company.com", role="admin")
    cookie = sign_panel_session(
        manager_id=str(admin_id),
        email="uuid-guard-post@v4company.com",
        signing_key=_SIGNING_KEY,
        aud="panel",
    )
    response = await client.post(
        url,
        data={"manager_id": "not-a-uuid", **extra},
        cookies={PANEL_SESSION_COOKIE_NAME: cookie},
        follow_redirects=False,
    )
    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.parametrize("url", ["/admin/access/bulk-copy", "/admin/access/meta/bulk-copy"])
async def test_post_bulk_copy_com_uuid_malformado_da_422(client: AsyncClient, url: str) -> None:
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        admin_id = await _create_manager(conn, email="uuid-guard-copy@v4company.com", role="admin")
    cookie = sign_panel_session(
        manager_id=str(admin_id),
        email="uuid-guard-copy@v4company.com",
        signing_key=_SIGNING_KEY,
        aud="panel",
    )
    response = await client.post(
        url,
        data={"from_manager_id": "not-a-uuid", "to_manager_id": str(uuid4())},
        cookies={PANEL_SESSION_COOKIE_NAME: cookie},
        follow_redirects=False,
    )
    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.parametrize("url", ["/admin/audit", "/admin/audit/export.csv"])
async def test_admin_audit_manager_id_malformado_da_422(client: AsyncClient, url: str) -> None:
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        admin_id = await _create_manager(conn, email="uuid-guard-aud@v4company.com", role="admin")
    cookie = sign_panel_session(
        manager_id=str(admin_id),
        email="uuid-guard-aud@v4company.com",
        signing_key=_SIGNING_KEY,
        aud="panel",
    )
    cookies = {PANEL_SESSION_COOKIE_NAME: cookie}
    ruim = await client.get(url, params={"manager_id": "zzz"}, cookies=cookies)
    assert ruim.status_code == 422
    # "Todos" (vazio) e UUID valido seguem funcionando.
    vazio = await client.get(url, params={"manager_id": ""}, cookies=cookies)
    assert vazio.status_code == 200
    valido = await client.get(url, params={"manager_id": str(admin_id)}, cookies=cookies)
    assert valido.status_code == 200
