"""Web panel accounts page tests."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.auth.panel_session import PANEL_SESSION_COOKIE_NAME, sign_panel_session
from src.db import connection
from src.db.repositories import (
    google_ads_accounts,
    google_oauth_connections,
    manager_account_access,
    manager_meta_account_access,
    managers,
    meta_ad_accounts,
)

_SIGNING_KEY = "x" * 32


@pytest.mark.integration
async def test_accounts_requires_auth(client: AsyncClient):
    response = await client.get("/accounts", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


@pytest.mark.integration
async def test_accounts_lists_oauth_connections_and_accounts(client: AsyncClient):
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="ac@v4company.com", full_name=None)
        await google_oauth_connections.upsert(
            conn,
            manager_id=mid,
            google_email="ac@gmail.com",
            refresh_token_enc=b"enc-1",
            scopes=["adwords"],
        )
        await google_ads_accounts.upsert_many(
            conn,
            [{"customer_id": "1234567890", "mcc_id": "M1", "descriptive_name": "Cliente Alpha"}],
        )
        await manager_account_access.grant(conn, manager_id=mid, customer_id="1234567890")

    cookie = sign_panel_session(
        manager_id=str(mid),
        email="ac@v4company.com",
        signing_key=_SIGNING_KEY,
    )
    response = await client.get(
        "/accounts",
        cookies={PANEL_SESSION_COOKIE_NAME: cookie},
    )
    assert response.status_code == 200
    assert "ac@gmail.com" in response.text  # OAuth connection email
    assert "1234567890" in response.text  # Account customer_id
    assert "Cliente Alpha" in response.text  # Account name


@pytest.mark.integration
async def test_accounts_revoke_connection(client: AsyncClient):
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="rv@v4company.com", full_name=None)
        oc = await google_oauth_connections.upsert(
            conn,
            manager_id=mid,
            google_email="rv@gmail.com",
            refresh_token_enc=b"enc-2",
            scopes=["adwords"],
        )

    cookie = sign_panel_session(
        manager_id=str(mid),
        email="rv@v4company.com",
        signing_key=_SIGNING_KEY,
    )
    response = await client.post(
        f"/accounts/{oc.id}/revoke",
        cookies={PANEL_SESSION_COOKIE_NAME: cookie},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/accounts"

    # Verify in DB
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        active = await google_oauth_connections.get_active_for_manager(conn, mid)
    assert active is None


@pytest.mark.integration
async def test_accounts_revoke_e_hx_aware(client: AsyncClient):
    """F96: chamada HTMX recebe 204+HX-Refresh, nunca o 303 (que o XHR seguiria).

    Seguindo o redirect, o htmx recebia a pagina `/accounts` INTEIRA e a
    template compensava injetando em `body.innerHTML` + `location.reload()`.
    """
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="hx@v4company.com", full_name=None)
        oc = await google_oauth_connections.upsert(
            conn,
            manager_id=mid,
            google_email="hx@gmail.com",
            refresh_token_enc=b"enc-hx",
            scopes=["adwords"],
        )

    cookie = sign_panel_session(
        manager_id=str(mid),
        email="hx@v4company.com",
        signing_key=_SIGNING_KEY,
    )
    response = await client.post(
        f"/accounts/{oc.id}/revoke",
        cookies={PANEL_SESSION_COOKIE_NAME: cookie},
        headers={"HX-Request": "true"},
        follow_redirects=False,
    )

    assert response.status_code == 204, "303 pra HTMX faz o XHR baixar a pagina inteira"
    assert response.headers["HX-Refresh"] == "true"
    assert "location" not in response.headers

    # E o efeito no banco continua sendo o mesmo.
    async with pool.acquire() as conn:
        active = await google_oauth_connections.get_active_for_manager(conn, mid)
    assert active is None


@pytest.mark.integration
async def test_accounts_cannot_revoke_others_connection(client: AsyncClient):
    """Manager A's connection can't be revoked by manager B."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid_a = uuid4()
        mid_b = uuid4()
        await managers.create(conn, manager_id=mid_a, email="a@v4company.com", full_name=None)
        await managers.create(conn, manager_id=mid_b, email="b@v4company.com", full_name=None)
        oc_a = await google_oauth_connections.upsert(
            conn,
            manager_id=mid_a,
            google_email="a@gmail.com",
            refresh_token_enc=b"enc-a",
            scopes=["adwords"],
        )

    cookie_b = sign_panel_session(
        manager_id=str(mid_b),
        email="b@v4company.com",
        signing_key=_SIGNING_KEY,
    )
    response = await client.post(
        f"/accounts/{oc_a.id}/revoke",
        cookies={PANEL_SESSION_COOKIE_NAME: cookie_b},
        follow_redirects=False,
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_accounts_shows_meta_accounts_when_granted(client: AsyncClient):
    """Gestor WITH a Meta grant sees the account name + Meta section heading."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="meta@v4company.com", full_name=None)
        await meta_ad_accounts.upsert_many(
            conn,
            [{"ad_account_id": "act_555", "account_name": "Loja Teste Meta"}],
        )
        await manager_meta_account_access.grant(conn, manager_id=mid, ad_account_id="act_555")

    cookie = sign_panel_session(
        manager_id=str(mid),
        email="meta@v4company.com",
        signing_key=_SIGNING_KEY,
    )
    response = await client.get(
        "/accounts",
        cookies={PANEL_SESSION_COOKIE_NAME: cookie},
    )
    assert response.status_code == 200
    assert "Contas Meta" in response.text
    assert "Loja Teste Meta" in response.text
    assert "act_555" in response.text


@pytest.mark.integration
async def test_accounts_shows_meta_empty_state_when_no_grant(client: AsyncClient):
    """Gestor with NO Meta grant sees an empty-state notice, not another manager's accounts."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="nometa@v4company.com", full_name=None)

    cookie = sign_panel_session(
        manager_id=str(mid),
        email="nometa@v4company.com",
        signing_key=_SIGNING_KEY,
    )
    response = await client.get(
        "/accounts",
        cookies={PANEL_SESSION_COOKIE_NAME: cookie},
    )
    assert response.status_code == 200
    assert "Contas Meta" in response.text
    assert "Nenhuma conta Meta" in response.text
