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
        aud="panel",
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
        aud="panel",
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
        aud="panel",
    )
    response = await client.get(
        "/audit",
        cookies={PANEL_SESSION_COOKIE_NAME: cookie},
    )
    assert response.status_code == 200
    assert "run_gaql_other_manager" not in response.text


@pytest.mark.integration
async def test_audit_export_csv_filters_by_status(client: AsyncClient):
    """CSV export with status=error must include only error rows, not success rows."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(
            conn, manager_id=mid, email="csv_status@v4company.com", full_name=None
        )
        await audit_log.record(
            conn,
            manager_id=mid,
            session_id=None,
            customer_id=None,
            action_type="read",
            operation="op_success_one",
            target_count=1,
            status="success",
            duration_ms=10,
        )
        await audit_log.record(
            conn,
            manager_id=mid,
            session_id=None,
            customer_id=None,
            action_type="read",
            operation="op_error_one",
            target_count=0,
            status="error",
            duration_ms=5,
            error_message="something went wrong",
        )

    cookie = sign_panel_session(
        manager_id=str(mid),
        email="csv_status@v4company.com",
        signing_key=_SIGNING_KEY,
        aud="panel",
    )
    response = await client.get(
        "/audit/export.csv?status=error",
        cookies={PANEL_SESSION_COOKIE_NAME: cookie},
    )
    assert response.status_code == 200
    assert "op_error_one" in response.text
    assert "op_success_one" not in response.text


@pytest.mark.integration
async def test_audit_pagination_follows_cursor_across_pages(client: AsyncClient):
    """Task 7 (PR 5): HTTP round-trip of the keyset cursor, not just the repo
    call in isolation. Exercises the part `test_audit_keyset.py` doesn't —
    FastAPI parsing `cursor_at`/`cursor_id` off a real querystring (datetime
    included) and the `cursor_pagination` macro emitting a working "Próxima"
    href — end to end, through the actual route.
    """
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(
            conn, manager_id=mid, email="cursor-http@v4company.com", full_name=None
        )
        # 51 > limit (50) da rota: so assim existe uma pagina 2 de verdade e o
        # link "Proxima" aparece. Uma unica transacao -> occurred_at empatado
        # nas 51 (F98/F88); a ordem fica so por id.
        async with conn.transaction():
            for i in range(51):
                await conn.execute(
                    "INSERT INTO audit_log (manager_id, action_type, operation, status, occurred_at) "
                    "VALUES ($1, 'read', $2, 'success', now())",
                    mid,
                    f"op_http_{i:02d}",
                )

    cookie = sign_panel_session(
        manager_id=str(mid),
        email="cursor-http@v4company.com",
        signing_key=_SIGNING_KEY,
        aud="panel",
    )
    page1 = await client.get("/audit", cookies={PANEL_SESSION_COOKIE_NAME: cookie})
    assert page1.status_code == 200
    assert "Próxima" in page1.text
    assert "cursor_at=" in page1.text, "o link real (nao so o texto) tem que estar no HTML"
    # op_http_50 foi a ULTIMA inserida (maior id) -> primeira na ordenacao
    # DESC -> topo da pagina 1.
    assert "op_http_50" in page1.text
    # op_http_00 foi a PRIMEIRA inserida (menor id) -> ultima na ordenacao ->
    # unica linha que sobra pra pagina 2 (51 linhas, limite 50).
    assert "op_http_00" not in page1.text

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        _, next_cursor = await audit_log.list_page_for_manager(
            conn, manager_id=mid, days=7, limit=50
        )
    assert next_cursor is not None, "51 linhas > limit 50: tem que sobrar cursor pra pagina 2"
    cursor_occurred_at, cursor_id = next_cursor

    page2 = await client.get(
        "/audit",
        params={"cursor_at": cursor_occurred_at.isoformat(), "cursor_id": cursor_id},
        cookies={PANEL_SESSION_COOKIE_NAME: cookie},
    )
    assert page2.status_code == 200
    assert "op_http_00" in page2.text
    assert "op_http_50" not in page2.text
    # Ultima pagina: sem mais linhas, o botao "Proxima" deve vir desabilitado
    # (sem href), nao um link pra um cursor que nao existe.
    assert "cursor_at=" not in page2.text
