"""Integration tests Sprint M.3 Task 3: meta_get_campaign_performance."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.db.repositories import (
    manager_meta_account_access,
    managers,
    meta_ad_accounts,
    meta_oauth_connections,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def pg() -> PostgresContainer:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture
async def db(pg: PostgresContainer):
    dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        await migrate.run_all()
        yield connection.get_pool()
    finally:
        await connection.close_pool()


async def _seed_manager_with_meta_conn(
    db,
    *,
    token_expires_in_days: int = 60,
    account_status: int = 1,  # ATIVO
):
    mid = uuid4()
    async with db.acquire() as conn:
        await managers.create(conn, manager_id=mid, email="t@v4company.com", full_name="Tester")
        token_expires = datetime.now(UTC) + timedelta(days=token_expires_in_days)
        await meta_oauth_connections.upsert(
            conn,
            manager_id=mid,
            fb_user_id="fb_user_test",
            fb_email="t@v4company.com",
            access_token_enc=b"fake_enc_bytes",
            token_expires_at=token_expires,
            scopes=["ads_read", "ads_management"],
        )
        await meta_ad_accounts.upsert_many(
            conn,
            [
                {
                    "ad_account_id": "act_123456",
                    "business_id": "bm_test",
                    "business_name": "Test BM",
                    "account_name": "Test Account",
                    "currency": "BRL",
                    "timezone_name": "America/Sao_Paulo",
                    "account_status": account_status,
                }
            ],
        )
        await manager_meta_account_access.grant(conn, manager_id=mid, ad_account_id="act_123456")
    return mid


@pytest.mark.integration
async def test_happy_path_returns_sorted_rows(db):
    """3 campaigns retornadas → ordenadas por spend_brl DESC."""
    from src.mcp.tools.meta_get_campaign_performance import (
        meta_get_campaign_performance,
    )

    mid = await _seed_manager_with_meta_conn(db)

    body = {
        "data": [
            {
                "campaign_id": "c1",
                "campaign_name": "Low spend",
                "objective": "OUTCOME_TRAFFIC",
                "effective_status": "ACTIVE",
                "spend": "100",
                "impressions": "1000",
                "clicks": "50",
                "ctr": "5.0",
                "cpc": "2.0",
                "actions": [{"action_type": "purchase", "value": "1"}],
                "action_values": [{"action_type": "purchase", "value": "50"}],
                "purchase_roas": [{"action_type": "omni_purchase", "value": "0.5"}],
            },
            {
                "campaign_id": "c2",
                "campaign_name": "High spend",
                "objective": "OUTCOME_SALES",
                "effective_status": "ACTIVE",
                "spend": "1000",
                "impressions": "10000",
                "clicks": "300",
                "ctr": "3.0",
                "cpc": "3.33",
                "actions": [{"action_type": "purchase", "value": "20"}],
                "action_values": [{"action_type": "purchase", "value": "4000"}],
                "purchase_roas": [{"action_type": "omni_purchase", "value": "4.0"}],
            },
            {
                "campaign_id": "c3",
                "campaign_name": "Mid spend",
                "objective": "OUTCOME_LEADS",
                "effective_status": "ACTIVE",
                "spend": "500",
                "impressions": "5000",
                "clicks": "100",
                "actions": [{"action_type": "lead", "value": "10"}],
            },
        ]
    }

    with patch(
        "src.mcp.tools.meta_get_campaign_performance.run_meta_graph_get",
        new=AsyncMock(return_value=body),
    ):
        result = await meta_get_campaign_performance(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
            date_range="LAST_7_DAYS",
        )

    assert result["status"] == "success"
    assert result["ad_account_id"] == "act_123456"
    assert result["ad_account_name"] == "Test Account"
    assert result["currency"] == "BRL"
    assert result["total_rows"] == 3
    # Sorted by spend_brl DESC
    assert result["rows"][0]["campaign_name"] == "High spend"
    assert result["rows"][1]["campaign_name"] == "Mid spend"
    assert result["rows"][2]["campaign_name"] == "Low spend"
    # Top row metrics
    top = result["rows"][0]
    assert top["spend_brl"] == 1000.0
    assert top["purchases"] == 20
    assert top["purchases_value_brl"] == 4000.0
    assert top["purchase_roas"] == 4.0
    assert top["effective_status_label"] == "ATIVO"


@pytest.mark.integration
async def test_never_injects_filtering(db):
    """M.3.1 (F53): filtering block removed entirely — Meta Insights rejects effective_status filter."""
    from src.mcp.tools.meta_get_campaign_performance import (
        meta_get_campaign_performance,
    )

    mid = await _seed_manager_with_meta_conn(db)

    captured_params: dict = {}

    async def capture_call(**kwargs):
        captured_params.update(kwargs["params"])
        return {"data": []}

    with patch(
        "src.mcp.tools.meta_get_campaign_performance.run_meta_graph_get",
        new=AsyncMock(side_effect=capture_call),
    ):
        await meta_get_campaign_performance(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
        )

    assert "filtering" not in captured_params
    assert "effective_status" not in captured_params["fields"]


@pytest.mark.integration
async def test_account_not_found_returns_error(db):
    """ad_account_id inexistente → error PT-BR friendly (sem Graph API call)."""
    from src.mcp.tools.meta_get_campaign_performance import (
        meta_get_campaign_performance,
    )

    mid = uuid4()
    async with db.acquire() as conn:
        await managers.create(conn, manager_id=mid, email="t@v4company.com", full_name="Tester")

    result = await meta_get_campaign_performance(
        manager_id=mid,
        session_id=uuid4(),
        ad_account_id="act_999999",  # not seeded
    )

    assert result["status"] == "error"
    assert "act_999999" in result["error_message"]
    assert "não encontrada" in result["error_message"]


@pytest.mark.integration
async def test_meta_api_error_returns_friendly_pt_br(db):
    """Graph API raise → error PT-BR friendly via to_friendly_meta_error."""
    from src.mcp.tools.meta_get_campaign_performance import (
        meta_get_campaign_performance,
    )
    from src.meta_ads.errors import MetaAdsFriendlyError

    mid = await _seed_manager_with_meta_conn(db)

    with patch(
        "src.mcp.tools.meta_get_campaign_performance.run_meta_graph_get",
        new=AsyncMock(
            side_effect=MetaAdsFriendlyError(
                "Limite Meta atingido. Tente novamente em alguns minutos.",
                retryable=True,
            )
        ),
    ):
        result = await meta_get_campaign_performance(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
        )

    assert result["status"] == "error"
    assert "Limite Meta" in result["error_message"]


@pytest.mark.integration
async def test_date_range_custom_overrides_preset(db):
    """start_date+end_date sobrescreve date_range preset → params.time_range custom."""
    from src.mcp.tools.meta_get_campaign_performance import (
        meta_get_campaign_performance,
    )

    mid = await _seed_manager_with_meta_conn(db)

    captured_params: dict = {}

    async def capture_call(**kwargs):
        captured_params.update(kwargs["params"])
        return {"data": []}

    with patch(
        "src.mcp.tools.meta_get_campaign_performance.run_meta_graph_get",
        new=AsyncMock(side_effect=capture_call),
    ):
        await meta_get_campaign_performance(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
            date_range="LAST_7_DAYS",  # should be overridden
            start_date="2026-03-01",
            end_date="2026-03-31",
        )

    assert "2026-03-01" in captured_params["time_range"]
    assert "2026-03-31" in captured_params["time_range"]
