"""Integration tests for /admin/access/meta routes (Meta access matrix)."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.auth.panel_session import PANEL_SESSION_COOKIE_NAME, sign_panel_session
from src.db import connection
from src.db.repositories import managers, meta_ad_accounts

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
        await meta_ad_accounts.upsert_many(
            conn,
            [
                {
                    "ad_account_id": "act_123456789",
                    "business_id": "biz_001",
                    "business_name": "Empresa Teste",
                    "account_name": "ML Antiguidades",
                    "currency": "BRL",
                    "timezone_name": "America/Sao_Paulo",
                    "account_status": 1,
                }
            ],
        )
    return admin_id, gestor_id


def _admin_cookie(admin_id):
    return sign_panel_session(
        manager_id=str(admin_id),
        email="admin@v4company.com",
        signing_key=_SIGNING_KEY,
    )


def _gestor_cookie(gestor_id):
    return sign_panel_session(
        manager_id=str(gestor_id),
        email="gestor@v4company.com",
        signing_key=_SIGNING_KEY,
    )


@pytest.mark.integration
async def test_admin_access_meta_renders(client: AsyncClient):
    pool = connection.get_pool()
    admin_id, _ = await _bootstrap_admin_and_gestor(pool)

    response = await client.get(
        "/admin/access/meta",
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
    )
    assert response.status_code == 200
    assert "Matriz de acessos" in response.text
    assert "ML Antiguidades" in response.text
    assert "act_123456789" in response.text


@pytest.mark.integration
async def test_admin_access_meta_requires_admin(client: AsyncClient):
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        gestor_id = uuid4()
        await managers.create(
            conn,
            manager_id=gestor_id,
            email="gestor2@v4company.com",
            full_name="Gestor2",
            role="gestor",
        )

    response = await client.get(
        "/admin/access/meta",
        cookies={PANEL_SESSION_COOKIE_NAME: _gestor_cookie(gestor_id)},
    )
    assert response.status_code == 403


@pytest.mark.integration
async def test_admin_access_meta_toggle_grant_then_revoke(client: AsyncClient):
    """POST /admin/access/meta/toggle: first call grants (returns checked), second revokes."""
    pool = connection.get_pool()
    admin_id, gestor_id = await _bootstrap_admin_and_gestor(pool)
    ad_account_id = "act_123456789"

    # First toggle → should grant access → checkbox has "checked"
    response1 = await client.post(
        "/admin/access/meta/toggle",
        data={"manager_id": str(gestor_id), "ad_account_id": ad_account_id},
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
    )
    assert response1.status_code == 200
    assert "checked" in response1.text

    # Second toggle → should revoke access → checkbox does NOT have "checked"
    response2 = await client.post(
        "/admin/access/meta/toggle",
        data={"manager_id": str(gestor_id), "ad_account_id": ad_account_id},
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
    )
    assert response2.status_code == 200
    assert "checked" not in response2.text


@pytest.mark.integration
async def test_admin_access_meta_by_manager_renders(client: AsyncClient):
    """GET /admin/access/meta/by-manager: renders 200 for admin."""
    pool = connection.get_pool()
    admin_id, _ = await _bootstrap_admin_and_gestor(pool)

    response = await client.get(
        "/admin/access/meta/by-manager",
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
    )
    assert response.status_code == 200
    assert "Acessos por gestor" in response.text
