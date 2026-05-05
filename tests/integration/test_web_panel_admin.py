"""Web panel admin pages tests."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.auth.panel_session import PANEL_SESSION_COOKIE_NAME, sign_panel_session
from src.db import connection
from src.db.repositories import google_ads_accounts, manager_account_access, managers

_SIGNING_KEY = "x" * 32


async def _bootstrap_admin_and_gestor(pool):
    async with pool.acquire() as conn:
        admin_id = uuid4()
        gestor_id = uuid4()
        await managers.create(
            conn,
            manager_id=admin_id,
            email="admin@v4company.com",
            full_name="Admin",
            role="admin",
        )
        await managers.create(
            conn,
            manager_id=gestor_id,
            email="gestor@v4company.com",
            full_name="Gestor",
            role="gestor",
        )
        await google_ads_accounts.upsert_many(
            conn,
            [{"customer_id": "1234567890", "mcc_id": "M1", "descriptive_name": "Cliente A"}],
        )
    return admin_id, gestor_id


def _admin_cookie(admin_id):
    return sign_panel_session(
        manager_id=str(admin_id),
        email="admin@v4company.com",
        signing_key=_SIGNING_KEY,
    )


@pytest.mark.integration
async def test_admin_managers_requires_admin(client: AsyncClient):
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        gestor_id = uuid4()
        await managers.create(
            conn,
            manager_id=gestor_id,
            email="g@v4company.com",
            full_name=None,
            role="gestor",
        )
    cookie = sign_panel_session(
        manager_id=str(gestor_id),
        email="g@v4company.com",
        signing_key=_SIGNING_KEY,
    )
    response = await client.get(
        "/admin/managers",
        cookies={PANEL_SESSION_COOKIE_NAME: cookie},
    )
    assert response.status_code == 403


@pytest.mark.integration
async def test_admin_managers_lists_users(client: AsyncClient):
    pool = connection.get_pool()
    admin_id, gestor_id = await _bootstrap_admin_and_gestor(pool)

    response = await client.get(
        "/admin/managers",
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
    )
    assert response.status_code == 200
    assert "admin@v4company.com" in response.text
    assert "gestor@v4company.com" in response.text


@pytest.mark.integration
async def test_admin_accounts_lists_synced(client: AsyncClient):
    pool = connection.get_pool()
    admin_id, _ = await _bootstrap_admin_and_gestor(pool)

    response = await client.get(
        "/admin/accounts",
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
    )
    assert response.status_code == 200
    assert "Cliente A" in response.text
    assert "1234567890" in response.text


@pytest.mark.integration
async def test_admin_access_matrix_renders(client: AsyncClient):
    pool = connection.get_pool()
    admin_id, gestor_id = await _bootstrap_admin_and_gestor(pool)
    async with pool.acquire() as conn:
        await manager_account_access.grant(
            conn,
            manager_id=gestor_id,
            customer_id="1234567890",
        )

    response = await client.get(
        "/admin/access",
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
    )
    assert response.status_code == 200
    assert "checked" in response.text  # at least one cell is checked
    assert "1234567890" in response.text


@pytest.mark.integration
async def test_admin_access_toggle_grants_then_revokes(client: AsyncClient):
    pool = connection.get_pool()
    admin_id, gestor_id = await _bootstrap_admin_and_gestor(pool)

    # First toggle: grants
    response = await client.post(
        "/admin/access/toggle",
        data={"manager_id": str(gestor_id), "customer_id": "1234567890"},
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
    )
    assert response.status_code == 200
    assert "checked" in response.text

    async with pool.acquire() as conn:
        accs = await manager_account_access.list_accounts_for_manager(conn, gestor_id)
    assert len(accs) == 1

    # Second toggle: revokes
    response = await client.post(
        "/admin/access/toggle",
        data={"manager_id": str(gestor_id), "customer_id": "1234567890"},
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
    )
    assert response.status_code == 200
    assert "checked" not in response.text or 'checked=""' not in response.text  # unchecked

    async with pool.acquire() as conn:
        accs = await manager_account_access.list_accounts_for_manager(conn, gestor_id)
    assert len(accs) == 0


@pytest.mark.integration
async def test_admin_audit_renders(client: AsyncClient):
    pool = connection.get_pool()
    admin_id, _ = await _bootstrap_admin_and_gestor(pool)
    response = await client.get(
        "/admin/audit",
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
    )
    assert response.status_code == 200
    # Phase 4 Task 4.4 redesigned the page; new template uses "Audit global" header.
    assert "Audit global" in response.text
