"""Integration tests for /admin/access/meta routes (Meta access matrix)."""

import json
from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.auth.panel_session import PANEL_SESSION_COOKIE_NAME, sign_panel_session
from src.db import connection
from src.db.repositories import manager_meta_account_access, managers, meta_ad_accounts

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
    assert '"checkbox" checked' in response1.text
    # F74: ver nota em test_web_panel_admin — handler agora e delegado.
    assert "data-v4-access-toggle" in response1.text
    assert "aria-label" in response1.text

    async with pool.acquire() as conn:
        grant_row = await conn.fetchrow(
            """SELECT operation, action_type, manager_id, customer_id, platform, params_summary
               FROM audit_log WHERE operation = $1 ORDER BY occurred_at DESC LIMIT 1""",
            "admin_access_grant",
        )
    assert grant_row is not None
    assert grant_row["action_type"] == "mutate"
    assert grant_row["manager_id"] == admin_id
    assert grant_row["customer_id"] == ad_account_id
    assert grant_row["platform"] == "meta"
    assert json.loads(grant_row["params_summary"])["granted"] is True

    # Second toggle → should revoke access → checkbox does NOT have "checked"
    response2 = await client.post(
        "/admin/access/meta/toggle",
        data={"manager_id": str(gestor_id), "ad_account_id": ad_account_id},
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
    )
    assert response2.status_code == 200
    assert '"checkbox" checked' not in response2.text

    async with pool.acquire() as conn:
        revoke_row = await conn.fetchrow(
            """SELECT operation, action_type, manager_id, customer_id, platform, params_summary
               FROM audit_log WHERE operation = $1 ORDER BY occurred_at DESC LIMIT 1""",
            "admin_access_revoke",
        )
    assert revoke_row is not None
    assert revoke_row["action_type"] == "mutate"
    assert revoke_row["manager_id"] == admin_id
    assert revoke_row["customer_id"] == ad_account_id
    assert revoke_row["platform"] == "meta"
    assert json.loads(revoke_row["params_summary"])["granted"] is False


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


@pytest.mark.integration
async def test_admin_access_meta_by_manager_conta_exclui_revogados(client: AsyncClient):
    """I1 (fix round 1): a contagem desta pagina nao pode incluir grant
    revogado — senao ela contradiz a pagina de detalhe por-gestor (que ja
    filtra revoked_at), tipo duas telas de offboarding discordando."""
    pool = connection.get_pool()
    admin_id, gestor_id = await _bootstrap_admin_and_gestor(pool)
    async with pool.acquire() as conn:
        await meta_ad_accounts.upsert_many(
            conn,
            [
                {
                    "ad_account_id": "act_222",
                    "business_id": "biz_001",
                    "business_name": "Empresa Teste",
                    "account_name": "Conta 2",
                    "currency": "BRL",
                    "timezone_name": "America/Sao_Paulo",
                    "account_status": 1,
                }
            ],
        )
        await manager_meta_account_access.bulk_grant(
            conn,
            manager_id=gestor_id,
            ad_account_ids=["act_123456789", "act_222"],
            granted_by=admin_id,
        )
        await manager_meta_account_access.revoke(
            conn, manager_id=gestor_id, ad_account_id="act_222"
        )

    response = await client.get(
        "/admin/access/meta/by-manager",
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
    )
    assert response.status_code == 200
    # total_accounts = 2 (act_123456789 do bootstrap + act_222); so 1 dos dois
    # grants do gestor segue vivo depois do revoke acima.
    assert "1 / 2 contas" in response.text
    assert "2 / 2 contas" not in response.text


@pytest.mark.integration
async def test_admin_access_meta_by_manager_denominador_exclui_desativada(client: AsyncClient):
    """M8: o denominador tem de ser o mesmo universo da pagina de detalhe.

    A matriz por gestor usa `list_all` (so ativas). Com `count(*)` cru aqui, o
    offboarding automatico fazia o denominador crescer pra sempre e as duas
    telas discordavam — mesma divergencia que o I1 fechou no numerador.
    """
    pool = connection.get_pool()
    admin_id, gestor_id = await _bootstrap_admin_and_gestor(pool)
    async with pool.acquire() as conn:
        await meta_ad_accounts.upsert_many(
            conn,
            [
                {
                    "ad_account_id": "act_saiu_denom",
                    "business_id": "biz_001",
                    "business_name": "Empresa Teste",
                    "account_name": "Ex-cliente",
                    "currency": "BRL",
                    "timezone_name": "America/Sao_Paulo",
                    "account_status": 1,
                }
            ],
        )
        await manager_meta_account_access.bulk_grant(
            conn, manager_id=gestor_id, ad_account_ids=["act_123456789"], granted_by=admin_id
        )
        await meta_ad_accounts.deactivate(conn, ad_account_ids=["act_saiu_denom"])

    response = await client.get(
        "/admin/access/meta/by-manager",
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
    )

    assert response.status_code == 200
    # 2 contas existem, 1 desativada: o denominador e 1, nao 2.
    assert "1 / 1 contas" in response.text
    assert "/ 2 contas" not in response.text


@pytest.mark.integration
async def test_admin_accounts_meta_renders_token_status(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /admin/accounts/meta with empty token → 200 with 'não configurado'."""
    monkeypatch.setenv("META_SYSTEM_USER_TOKEN", "")
    pool = connection.get_pool()
    admin_id, _ = await _bootstrap_admin_and_gestor(pool)

    response = await client.get(
        "/admin/accounts/meta",
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
    )
    assert response.status_code == 200
    assert "Token do system user" in response.text
    assert "não configurado" in response.text


@pytest.mark.integration
async def test_admin_access_meta_bulk_grant_records_audit(client: AsyncClient):
    pool = connection.get_pool()
    admin_id, gestor_id = await _bootstrap_admin_and_gestor(pool)
    async with pool.acquire() as conn:
        await meta_ad_accounts.upsert_many(
            conn,
            [
                {
                    "ad_account_id": "act_987654321",
                    "business_id": "biz_001",
                    "business_name": "Empresa Teste",
                    "account_name": "Outra Conta",
                    "currency": "BRL",
                    "timezone_name": "America/Sao_Paulo",
                    "account_status": 1,
                }
            ],
        )

    response = await client.post(
        "/admin/access/meta/bulk-grant",
        data={
            "manager_id": str(gestor_id),
            "ad_account_ids": ["act_123456789", "act_987654321"],
        },
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
    )
    assert response.status_code == 303

    async with pool.acquire() as conn:
        access_rows = await conn.fetch(
            "SELECT ad_account_id FROM manager_meta_account_access WHERE manager_id = $1",
            gestor_id,
        )
        row = await conn.fetchrow(
            """SELECT operation, action_type, manager_id, customer_id, platform, params_summary
               FROM audit_log WHERE operation = $1 ORDER BY occurred_at DESC LIMIT 1""",
            "admin_access_bulk_grant",
        )
    assert {r["ad_account_id"] for r in access_rows} == {"act_123456789", "act_987654321"}
    assert row is not None
    assert row["action_type"] == "mutate"
    assert row["manager_id"] == admin_id
    assert row["customer_id"] is None
    assert row["platform"] == "meta"
    summary = json.loads(row["params_summary"])
    assert summary["target_manager_id"] == str(gestor_id)
    assert summary["count"] == 2
    assert set(summary["ids"]) == {"act_123456789", "act_987654321"}


@pytest.mark.integration
async def test_admin_access_meta_bulk_copy_records_audit(client: AsyncClient):
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
        await manager_meta_account_access.grant(
            conn,
            manager_id=gestor_id,
            ad_account_id="act_123456789",
        )

    response = await client.post(
        "/admin/access/meta/bulk-copy",
        data={"from_manager_id": str(gestor_id), "to_manager_id": str(other_id)},
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
    )
    assert response.status_code == 303

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT operation, action_type, manager_id, customer_id, platform, params_summary
               FROM audit_log WHERE operation = $1 ORDER BY occurred_at DESC LIMIT 1""",
            "admin_access_bulk_copy",
        )
    assert row is not None
    assert row["action_type"] == "mutate"
    assert row["manager_id"] == admin_id
    assert row["customer_id"] is None
    assert row["platform"] == "meta"
    summary = json.loads(row["params_summary"])
    assert summary["from_manager_id"] == str(gestor_id)
    assert summary["to_manager_id"] == str(other_id)
