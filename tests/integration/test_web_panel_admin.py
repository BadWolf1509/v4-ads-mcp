"""Web panel admin pages tests."""

import json
from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.auth.panel_session import PANEL_SESSION_COOKIE_NAME, sign_panel_session
from src.db import connection
from src.db.repositories import (
    google_ads_accounts,
    manager_account_access,
    managers,
    meta_ad_accounts,
)

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
    assert '"checkbox" checked' in response.text
    # F74: o fragmento tem que sobreviver ao swap. Desde 2026-08-11 o toast e o
    # revert-on-fail vivem num listener delegado em v4-panel.js, entao o que o
    # fragmento precisa carregar e o marcador — nao mais um hx-on re-emitido.
    assert "data-v4-access-toggle" in response.text
    assert "aria-label" in response.text

    async with pool.acquire() as conn:
        accs = await manager_account_access.list_accounts_for_manager(conn, gestor_id)
        grant_row = await conn.fetchrow(
            """SELECT operation, action_type, manager_id, customer_id, params_summary
               FROM audit_log WHERE operation = $1 ORDER BY occurred_at DESC LIMIT 1""",
            "admin_access_grant",
        )
    assert len(accs) == 1
    assert grant_row is not None
    assert grant_row["action_type"] == "mutate"
    assert grant_row["manager_id"] == admin_id
    assert grant_row["customer_id"] == "1234567890"
    assert json.loads(grant_row["params_summary"])["granted"] is True

    # Second toggle: revokes
    response = await client.post(
        "/admin/access/toggle",
        data={"manager_id": str(gestor_id), "customer_id": "1234567890"},
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
    )
    assert response.status_code == 200
    assert '"checkbox" checked' not in response.text  # unchecked

    async with pool.acquire() as conn:
        accs = await manager_account_access.list_accounts_for_manager(conn, gestor_id)
        revoke_row = await conn.fetchrow(
            """SELECT operation, action_type, manager_id, customer_id, params_summary
               FROM audit_log WHERE operation = $1 ORDER BY occurred_at DESC LIMIT 1""",
            "admin_access_revoke",
        )
    assert len(accs) == 0
    assert revoke_row is not None
    assert revoke_row["action_type"] == "mutate"
    assert revoke_row["manager_id"] == admin_id
    assert revoke_row["customer_id"] == "1234567890"
    assert json.loads(revoke_row["params_summary"])["granted"] is False


@pytest.mark.integration
async def test_admin_audit_renders(client: AsyncClient):
    pool = connection.get_pool()
    admin_id, _ = await _bootstrap_admin_and_gestor(pool)
    response = await client.get(
        "/admin/audit",
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
    )
    assert response.status_code == 200
    # Phase 4 Task 4.4 redesigned the page; new template uses "Auditoria global" header.
    assert "Auditoria global" in response.text


@pytest.mark.integration
async def test_admin_managers_toggle_active_records_audit(client: AsyncClient):
    pool = connection.get_pool()
    admin_id, gestor_id = await _bootstrap_admin_and_gestor(pool)

    response = await client.post(
        f"/admin/managers/{gestor_id}/toggle-active",
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
    )
    assert response.status_code == 303

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT operation, action_type, manager_id, customer_id, params_summary
               FROM audit_log WHERE operation = $1 ORDER BY occurred_at DESC LIMIT 1""",
            "admin_manager_toggle_active",
        )
    assert row is not None
    assert row["action_type"] == "mutate"
    assert row["manager_id"] == admin_id
    assert row["customer_id"] is None
    summary = json.loads(row["params_summary"])
    assert summary["target_manager_id"] == str(gestor_id)
    assert summary["target_email"] == "gestor@v4company.com"


@pytest.mark.integration
async def test_admin_managers_toggle_role_records_audit(client: AsyncClient):
    pool = connection.get_pool()
    admin_id, gestor_id = await _bootstrap_admin_and_gestor(pool)

    response = await client.post(
        f"/admin/managers/{gestor_id}/toggle-role",
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
    )
    assert response.status_code == 303

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT operation, action_type, manager_id, customer_id, params_summary
               FROM audit_log WHERE operation = $1 ORDER BY occurred_at DESC LIMIT 1""",
            "admin_manager_toggle_role",
        )
    assert row is not None
    assert row["action_type"] == "mutate"
    assert row["manager_id"] == admin_id
    summary = json.loads(row["params_summary"])
    assert summary["target_manager_id"] == str(gestor_id)
    assert summary["target_email"] == "gestor@v4company.com"


@pytest.mark.integration
async def test_admin_managers_toggle_htmx_returns_hx_redirect(client: AsyncClient):
    pool = connection.get_pool()
    admin_id, gestor_id = await _bootstrap_admin_and_gestor(pool)

    async with pool.acquire() as conn:
        before = await conn.fetchrow(
            "SELECT is_active, role FROM managers WHERE id = $1", gestor_id
        )
    assert before is not None

    response = await client.post(
        f"/admin/managers/{gestor_id}/toggle-active",
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 204
    assert response.headers["HX-Redirect"] == "/admin/managers"
    assert "toast" in response.headers["HX-Trigger"]

    async with pool.acquire() as conn:
        after_active = await conn.fetchrow(
            "SELECT is_active FROM managers WHERE id = $1", gestor_id
        )
    assert after_active is not None
    assert after_active["is_active"] != before["is_active"]

    response = await client.post(
        f"/admin/managers/{gestor_id}/toggle-role",
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 204
    assert response.headers["HX-Redirect"] == "/admin/managers"
    assert "toast" in response.headers["HX-Trigger"]

    async with pool.acquire() as conn:
        after_role = await conn.fetchrow("SELECT role FROM managers WHERE id = $1", gestor_id)
    assert after_role is not None
    assert after_role["role"] != before["role"]


@pytest.mark.integration
async def test_admin_access_bulk_grant_records_audit(client: AsyncClient):
    pool = connection.get_pool()
    admin_id, gestor_id = await _bootstrap_admin_and_gestor(pool)
    async with pool.acquire() as conn:
        await google_ads_accounts.upsert_many(
            conn,
            [{"customer_id": "1111111111", "mcc_id": "M1", "descriptive_name": "Cliente B"}],
        )

    response = await client.post(
        "/admin/access/bulk-grant",
        data={
            "manager_id": str(gestor_id),
            "customer_ids": ["1234567890", "1111111111"],
        },
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
    )
    assert response.status_code == 303

    async with pool.acquire() as conn:
        accs = await manager_account_access.list_accounts_for_manager(conn, gestor_id)
        row = await conn.fetchrow(
            """SELECT operation, action_type, manager_id, customer_id, params_summary
               FROM audit_log WHERE operation = $1 ORDER BY occurred_at DESC LIMIT 1""",
            "admin_access_bulk_grant",
        )
    assert len(accs) == 2
    assert row is not None
    assert row["action_type"] == "mutate"
    assert row["manager_id"] == admin_id
    assert row["customer_id"] is None
    summary = json.loads(row["params_summary"])
    assert summary["target_manager_id"] == str(gestor_id)
    assert summary["count"] == 2
    assert set(summary["ids"]) == {"1234567890", "1111111111"}


@pytest.mark.integration
async def test_admin_access_bulk_copy_records_audit(client: AsyncClient):
    pool = connection.get_pool()
    admin_id, gestor_id = await _bootstrap_admin_and_gestor(pool)
    async with pool.acquire() as conn:
        other_id = uuid4()
        await managers.create(
            conn,
            manager_id=other_id,
            email="other@v4company.com",
            full_name="Other",
            role="gestor",
        )
        await manager_account_access.grant(
            conn,
            manager_id=gestor_id,
            customer_id="1234567890",
        )

    response = await client.post(
        "/admin/access/bulk-copy",
        data={"from_manager_id": str(gestor_id), "to_manager_id": str(other_id)},
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
    )
    assert response.status_code == 303

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT operation, action_type, manager_id, customer_id, params_summary
               FROM audit_log WHERE operation = $1 ORDER BY occurred_at DESC LIMIT 1""",
            "admin_access_bulk_copy",
        )
    assert row is not None
    assert row["action_type"] == "mutate"
    assert row["manager_id"] == admin_id
    assert row["customer_id"] is None
    summary = json.loads(row["params_summary"])
    assert summary["from_manager_id"] == str(gestor_id)
    assert summary["to_manager_id"] == str(other_id)


@pytest.mark.integration
async def test_admin_invites_new_records_audit(client: AsyncClient):
    pool = connection.get_pool()
    admin_id, _ = await _bootstrap_admin_and_gestor(pool)

    response = await client.post(
        "/admin/invites/new",
        data={"email": "novo.gestor@v4company.com", "full_name": "Novo Gestor"},
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/invites?ok=1"

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT operation, action_type, manager_id, customer_id, params_summary
               FROM audit_log WHERE operation = $1 ORDER BY occurred_at DESC LIMIT 1""",
            "admin_invite_new",
        )
    assert row is not None
    assert row["action_type"] == "mutate"
    assert row["manager_id"] == admin_id
    summary = json.loads(row["params_summary"])
    assert summary["email"] == "novo.gestor@v4company.com"


@pytest.mark.integration
async def test_admin_invites_cancel_records_audit(client: AsyncClient):
    pool = connection.get_pool()
    admin_id, _ = await _bootstrap_admin_and_gestor(pool)
    async with pool.acquire() as conn:
        invite = await managers.create_invited(
            conn,
            email="cancelado@v4company.com",
            invited_by=admin_id,
            full_name="A Cancelar",
        )

    response = await client.post(
        f"/admin/invites/{invite.id}/cancel",
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/invites"

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT operation, action_type, manager_id, customer_id, params_summary
               FROM audit_log WHERE operation = $1 ORDER BY occurred_at DESC LIMIT 1""",
            "admin_invite_cancel",
        )
    assert row is not None
    assert row["action_type"] == "mutate"
    assert row["manager_id"] == admin_id
    summary = json.loads(row["params_summary"])
    assert summary["email"] == "cancelado@v4company.com"


@pytest.mark.integration
async def test_admin_invites_cancel_htmx_returns_refresh(client: AsyncClient):
    pool = connection.get_pool()
    admin_id, _ = await _bootstrap_admin_and_gestor(pool)
    async with pool.acquire() as conn:
        invite = await managers.create_invited(
            conn,
            email="cancelado.htmx@v4company.com",
            invited_by=admin_id,
            full_name="A Cancelar Htmx",
        )

    response = await client.post(
        f"/admin/invites/{invite.id}/cancel",
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 204
    assert response.headers["HX-Refresh"] == "true"

    async with pool.acquire() as conn:
        remaining = await conn.fetchval("SELECT 1 FROM managers WHERE id = $1", invite.id)
        row = await conn.fetchrow(
            """SELECT operation, action_type, manager_id, params_summary
               FROM audit_log WHERE operation = $1 ORDER BY occurred_at DESC LIMIT 1""",
            "admin_invite_cancel",
        )
    assert remaining is None
    assert row is not None
    assert row["action_type"] == "mutate"
    assert row["manager_id"] == admin_id
    summary = json.loads(row["params_summary"])
    assert summary["email"] == "cancelado.htmx@v4company.com"


@pytest.mark.integration
async def test_admin_invites_shows_age_and_onboarding(client: AsyncClient):
    pool = connection.get_pool()
    admin_id, _ = await _bootstrap_admin_and_gestor(pool)
    async with pool.acquire() as conn:
        invite = await managers.create_invited(
            conn,
            email="antigo@v4company.com",
            invited_by=admin_id,
            full_name="Convite Antigo",
        )
        await conn.execute(
            "UPDATE managers SET invited_at = now() - interval '10 days' WHERE id = $1",
            invite.id,
        )

    response = await client.get(
        "/admin/invites",
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
    )
    assert response.status_code == 200
    assert "há 10 dias" in response.text
    assert "/login" in response.text
    assert "Copiar mensagem" in response.text


@pytest.mark.integration
async def test_admin_invites_flash_messages(client: AsyncClient):
    pool = connection.get_pool()
    admin_id, _ = await _bootstrap_admin_and_gestor(pool)

    response = await client.get(
        "/admin/invites?error=bad_domain",
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
    )
    assert response.status_code == 200
    assert "Só emails @v4company.com" in response.text

    response = await client.get(
        "/admin/invites?ok=1",
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
    )
    assert response.status_code == 200
    assert "Convite criado." in response.text

    response = await client.get(
        "/admin/invites?error=exists",
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
    )
    assert response.status_code == 200
    assert "Esse email já está cadastrado" in response.text

    # Anti-XSS: unknown/malicious codes never echo the raw query param value.
    response = await client.get(
        "/admin/invites?error=<script>alert(1)</script>",
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
    )
    assert response.status_code == 200
    assert "alert(1)" not in response.text


@pytest.mark.integration
async def test_admin_access_flash_same_manager(client: AsyncClient):
    pool = connection.get_pool()
    admin_id, _ = await _bootstrap_admin_and_gestor(pool)
    async with pool.acquire() as conn:
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

    response = await client.get(
        "/admin/access?error=same_manager",
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
    )
    assert response.status_code == 200
    assert "Gestor de origem e destino são o mesmo" in response.text

    response = await client.get(
        "/admin/access/meta?error=same_manager",
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
    )
    assert response.status_code == 200
    assert "Gestor de origem e destino são o mesmo" in response.text
