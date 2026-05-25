"""Web panel audit page tests."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.auth.panel_session import PANEL_SESSION_COOKIE_NAME, sign_panel_session
from src.db import connection
from src.db.repositories import audit_log, google_ads_accounts, managers

_SIGNING_KEY = "x" * 32


@pytest.mark.integration
async def test_audit_requires_auth(client: AsyncClient):
    response = await client.get("/audit", follow_redirects=False)
    assert response.status_code == 302


@pytest.mark.integration
async def test_audit_lists_managers_own_events(client: AsyncClient):
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="au@v4company.com", full_name=None)
        await google_ads_accounts.upsert_many(
            conn,
            [{"customer_id": "1234567890", "mcc_id": "M1", "descriptive_name": "Cliente Alpha"}],
        )
        await audit_log.record(
            conn,
            manager_id=mid,
            session_id=None,
            customer_id="1234567890",
            action_type="read",
            operation="get_account_overview",
            target_count=1,
            status="success",
            duration_ms=42,
        )
        await audit_log.record(
            conn,
            manager_id=mid,
            session_id=None,
            customer_id="1234567890",
            action_type="mutate",
            operation="update_campaign_status",
            target_count=3,
            status="success",
            duration_ms=120,
            provider_request_id="req-fake",
        )

    cookie = sign_panel_session(
        manager_id=str(mid),
        email="au@v4company.com",
        signing_key=_SIGNING_KEY,
    )
    response = await client.get(
        "/audit",
        cookies={PANEL_SESSION_COOKIE_NAME: cookie},
    )
    assert response.status_code == 200
    assert "get_account_overview" in response.text
    assert "update_campaign_status" in response.text
    assert "Cliente Alpha" in response.text  # account name shown


@pytest.mark.integration
async def test_audit_filters_by_action_type(client: AsyncClient):
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="afilt@v4company.com", full_name=None)
        await audit_log.record(
            conn,
            manager_id=mid,
            session_id=None,
            customer_id=None,
            action_type="read",
            operation="run_gaql",
            target_count=1,
            status="success",
            duration_ms=10,
        )
        await audit_log.record(
            conn,
            manager_id=mid,
            session_id=None,
            customer_id=None,
            action_type="mutate",
            operation="update_campaign_budget",
            target_count=1,
            status="success",
            duration_ms=100,
        )

    cookie = sign_panel_session(
        manager_id=str(mid),
        email="afilt@v4company.com",
        signing_key=_SIGNING_KEY,
    )
    # Filter to mutate only
    response = await client.get(
        "/audit?action_type=mutate",
        cookies={PANEL_SESSION_COOKIE_NAME: cookie},
    )
    assert response.status_code == 200
    assert "update_campaign_budget" in response.text
    assert "run_gaql" not in response.text


@pytest.mark.integration
async def test_audit_does_not_show_other_managers_events(client: AsyncClient):
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid_a = uuid4()
        mid_b = uuid4()
        await managers.create(conn, manager_id=mid_a, email="a@v4company.com", full_name=None)
        await managers.create(conn, manager_id=mid_b, email="b@v4company.com", full_name=None)
        await audit_log.record(
            conn,
            manager_id=mid_b,
            session_id=None,
            customer_id=None,
            action_type="read",
            operation="run_gaql_other_manager",
            target_count=1,
            status="success",
            duration_ms=10,
        )

    # Login as A; expect B's event NOT to appear
    cookie = sign_panel_session(
        manager_id=str(mid_a),
        email="a@v4company.com",
        signing_key=_SIGNING_KEY,
    )
    response = await client.get(
        "/audit",
        cookies={PANEL_SESSION_COOKIE_NAME: cookie},
    )
    assert response.status_code == 200
    assert "run_gaql_other_manager" not in response.text
