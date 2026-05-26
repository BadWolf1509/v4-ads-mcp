"""Integration tests Sprint M.3 Task 5: meta_get_ad_performance."""

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


async def _seed_manager_with_meta_conn(db):
    mid = uuid4()
    async with db.acquire() as conn:
        await managers.create(conn, manager_id=mid, email="t@v4company.com", full_name="Tester")
        await meta_oauth_connections.upsert(
            conn,
            manager_id=mid,
            fb_user_id="fb_user_test",
            fb_email="t@v4company.com",
            access_token_enc=b"fake_enc_bytes",
            token_expires_at=datetime.now(UTC) + timedelta(days=60),
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
                    "account_status": 1,
                }
            ],
        )
        await manager_meta_account_access.grant(conn, manager_id=mid, ad_account_id="act_123456")
    return mid


@pytest.mark.integration
async def test_happy_path_returns_ad_rows_sorted(db):
    """2 ads retornados → ordenados por spend DESC + creative_id presence."""
    from src.mcp.tools.meta_get_ad_performance import meta_get_ad_performance

    mid = await _seed_manager_with_meta_conn(db)

    body = {
        "data": [
            {
                "ad_id": "ad1",
                "ad_name": "Ad Low",
                "adset_id": "as1",
                "adset_name": "AS 1",
                "campaign_id": "c1",
                "campaign_name": "Camp 1",
                "creative_id": "cr1",
                "effective_status": "ACTIVE",
                "spend": "50",
                "impressions": "500",
                "clicks": "10",
            },
            {
                "ad_id": "ad2",
                "ad_name": "Ad High",
                "adset_id": "as1",
                "adset_name": "AS 1",
                "campaign_id": "c1",
                "campaign_name": "Camp 1",
                "creative_id": "cr2",
                "effective_status": "ACTIVE",
                "spend": "500",
                "impressions": "5000",
                "clicks": "120",
                "actions": [{"action_type": "purchase", "value": "5"}],
            },
        ]
    }

    with patch(
        "src.mcp.tools.meta_get_ad_performance.run_meta_graph_get",
        new=AsyncMock(return_value=body),
    ):
        result = await meta_get_ad_performance(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
        )

    assert result["status"] == "success"
    assert result["total_rows"] == 2
    assert result["rows"][0]["ad_name"] == "Ad High"
    assert result["rows"][0]["spend_brl"] == 500.0
    assert result["rows"][0]["creative_id"] == "cr2"
    assert result["rows"][0]["ad_set_id"] == "as1"
    assert result["rows"][0]["campaign_id"] == "c1"


@pytest.mark.integration
async def test_ad_missing_creative_id_returns_none(db):
    """Ad sem creative_id (data issue / draft) → creative_id=None acceptable."""
    from src.mcp.tools.meta_get_ad_performance import meta_get_ad_performance

    mid = await _seed_manager_with_meta_conn(db)

    body = {
        "data": [
            {
                "ad_id": "ad1",
                "ad_name": "Ad",
                "adset_id": "as1",
                "adset_name": "AS 1",
                "campaign_id": "c1",
                "campaign_name": "C",
                "effective_status": "PAUSED",
                "spend": "0",
                # creative_id absent
            }
        ]
    }

    with patch(
        "src.mcp.tools.meta_get_ad_performance.run_meta_graph_get",
        new=AsyncMock(return_value=body),
    ):
        result = await meta_get_ad_performance(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
        )

    assert result["status"] == "success"
    assert result["rows"][0]["creative_id"] is None
    assert result["rows"][0]["effective_status_label"] == "PAUSADO"


@pytest.mark.integration
async def test_level_ad_in_params(db):
    """Confirma level='ad' passado à Graph API."""
    from src.mcp.tools.meta_get_ad_performance import meta_get_ad_performance

    mid = await _seed_manager_with_meta_conn(db)

    captured_params: dict = {}

    async def capture_call(**kwargs):
        captured_params.update(kwargs["params"])
        return {"data": []}

    with patch(
        "src.mcp.tools.meta_get_ad_performance.run_meta_graph_get",
        new=AsyncMock(side_effect=capture_call),
    ):
        await meta_get_ad_performance(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
        )

    assert captured_params["level"] == "ad"
    assert "ad_id" in captured_params["fields"]
    assert "creative_id" in captured_params["fields"]


@pytest.mark.integration
async def test_account_not_found_returns_error(db):
    """ad_account_id inexistente → error PT-BR."""
    from src.mcp.tools.meta_get_ad_performance import meta_get_ad_performance

    mid = uuid4()
    async with db.acquire() as conn:
        await managers.create(conn, manager_id=mid, email="t@v4company.com", full_name="Tester")

    result = await meta_get_ad_performance(
        manager_id=mid,
        session_id=uuid4(),
        ad_account_id="act_999999",
    )

    assert result["status"] == "error"
    assert "act_999999" in result["error_message"]
