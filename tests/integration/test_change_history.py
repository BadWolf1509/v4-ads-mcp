"""Integration tests for get_change_history (real Postgres, mocked SDK)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.db.repositories import managers, mcp_sessions
from src.mcp.context import McpRequestContext, clear_current, set_current


@pytest.fixture
async def pg() -> PostgresContainer:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture
async def db(pg):
    dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        await migrate.run_all()
        yield connection.get_pool()
    finally:
        await connection.close_pool()


@pytest.fixture
async def session_ctx(db):
    pool = db
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="t@v4.com", full_name=None)
        from src.auth.sessions import generate_session_token, hash_session_token

        token = generate_session_token()
        sess = await mcp_sessions.create(
            conn, manager_id=mid, token_hash=hash_session_token(token), label="t"
        )
    ctx = McpRequestContext(manager_id=mid, session_id=sess.id)
    set_current(ctx)
    yield ctx
    clear_current()


def _make_change_event_row(*, user, ct, rtype, op, resource_path, campaign="", ad_group=""):
    """Build a mock SDK row with .change_event.* fields the formatter reads."""
    ce = SimpleNamespace(
        change_date_time="2026-05-08 14:23:11+00:00",
        user_email=user,
        client_type=SimpleNamespace(name=ct),
        change_resource_type=SimpleNamespace(name=rtype),
        change_resource_name=resource_path,
        resource_change_operation=SimpleNamespace(name=op),
        changed_fields=SimpleNamespace(paths=["status", "campaign_budget"]),
        campaign=campaign,
        ad_group=ad_group,
    )
    return SimpleNamespace(change_event=ce)


@pytest.mark.integration
async def test_get_change_history_aggregates_with_auto_apply(db, session_ctx):
    """End-to-end: mock 4 change_events (1 auto-apply, 3 manual) -> summary correct + audit row."""
    from src.mcp.tools.get_change_history import get_change_history

    mock_events = [
        _make_change_event_row(
            user="fulano@v4company.com",
            ct="GOOGLE_ADS_WEB_CLIENT",
            rtype="CAMPAIGN",
            op="UPDATE",
            resource_path="customers/123/campaigns/100",
            campaign="customers/123/campaigns/100",
        ),
        _make_change_event_row(
            user="fulano@v4company.com",
            ct="GOOGLE_ADS_WEB_CLIENT",
            rtype="AD_GROUP_CRITERION",
            op="CREATE",
            resource_path="customers/123/adGroupCriteria/200~300",
            ad_group="customers/123/adGroups/200",
        ),
        _make_change_event_row(
            user="ana@v4company.com",
            ct="GOOGLE_ADS_WEB_CLIENT",
            rtype="BIDDING_STRATEGY",
            op="UPDATE",
            resource_path="customers/123/biddingStrategies/400",
        ),
        _make_change_event_row(
            user="google@google.com",
            ct="GOOGLE_ADS_RECOMMENDATIONS",
            rtype="CAMPAIGN",
            op="UPDATE",
            resource_path="customers/123/campaigns/100",
            campaign="customers/123/campaigns/100",
        ),
    ]

    # Mock the SDK stream to yield one batch with our 4 rows
    batch = MagicMock(results=mock_events)
    fake_stream = [batch]
    fake_service = MagicMock()
    fake_service.search_stream = MagicMock(return_value=fake_stream)
    fake_client = MagicMock()
    fake_client.get_service = MagicMock(return_value=fake_service)
    fake_client.get_type = MagicMock(return_value=MagicMock())

    # Name resolution: stub _resolve_names to return one campaign name
    async def fake_resolve_names(**kwargs):
        return {("campaign", "100"): "Pesquisa - Marca"}

    with (
        patch(
            "src.google_ads.reports.build_client_for_manager",
            AsyncMock(return_value=fake_client),
        ),
        patch(
            "src.mcp.tools.get_change_history._resolve_names",
            fake_resolve_names,
        ),
    ):
        result = await get_change_history(
            {
                "customer_id": "1234567890",
                "date_range": "LAST_7_DAYS",
            }
        )

    assert result["customer_id"] == "1234567890"
    assert result["summary"]["total_changes"] == 4
    assert result["summary"]["auto_applied_count"] == 1
    assert result["summary"]["by_user"] == {
        "fulano@v4company.com": 2,
        "ana@v4company.com": 1,
        "auto-apply": 1,
    }
    # Campaign row uses resolved name
    campaign_rows = [r for r in result["rows"] if r["resource_type"] == "CAMPAIGN"]
    assert any(r["resource_name"] == "Pesquisa - Marca" for r in campaign_rows)

    # Audit row created (sensitive read)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT operation, action_type, status FROM audit_log "
            "WHERE operation = 'get_change_history'"
        )
    assert len(rows) == 1
    assert rows[0]["action_type"] == "read"
    assert rows[0]["status"] == "success"
