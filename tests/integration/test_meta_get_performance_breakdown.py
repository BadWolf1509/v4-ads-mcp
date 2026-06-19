"""Integration tests Sprint M.4: meta_get_performance_breakdown."""

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


async def _seed(db):
    mid = uuid4()
    async with db.acquire() as conn:
        await managers.create(conn, manager_id=mid, email="t@v4company.com", full_name="T")
        await meta_oauth_connections.upsert(
            conn,
            manager_id=mid,
            fb_user_id="fb_test",
            fb_email="t@v4company.com",
            access_token_enc=b"fake",
            token_expires_at=datetime.now(UTC) + timedelta(days=60),
            scopes=["ads_read"],
        )
        await meta_ad_accounts.upsert_many(
            conn,
            [
                {
                    "ad_account_id": "act_123456",
                    "business_id": "bm",
                    "business_name": "BM",
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
async def test_happy_path_platform_breakdown_sorted_and_surfaced(db):
    from src.mcp.tools.meta_get_performance_breakdown import meta_get_performance_breakdown

    mid = await _seed(db)
    body = {
        "data": [
            {
                "campaign_id": "c1",
                "campaign_name": "C1",
                "effective_status": "ACTIVE",
                "spend": "100",
                "publisher_platform": "facebook",
            },
            {
                "campaign_id": "c1",
                "campaign_name": "C1",
                "effective_status": "ACTIVE",
                "spend": "300",
                "publisher_platform": "instagram",
            },
        ]
    }
    with patch(
        "src.mcp.tools.meta_get_performance_breakdown.run_meta_graph_get",
        new=AsyncMock(return_value=body),
    ):
        result = await meta_get_performance_breakdown(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
            breakdown="platform",
            date_range="LAST_7_DAYS",
        )
    assert result["status"] == "success"
    assert result["level"] == "campaign"
    assert result["breakdown"] == "platform"
    assert result["total_rows"] == 2
    assert result["rows"][0]["breakdown"] == {"publisher_platform": "instagram"}  # 300 first
    assert result["rows"][1]["breakdown"] == {"publisher_platform": "facebook"}


@pytest.mark.integration
async def test_injects_breakdowns_param_for_level(db):
    from src.mcp.tools.meta_get_performance_breakdown import meta_get_performance_breakdown

    mid = await _seed(db)
    captured: dict = {}

    async def capture(**kwargs):
        captured.update(kwargs["params"])
        return {"data": []}

    with patch(
        "src.mcp.tools.meta_get_performance_breakdown.run_meta_graph_get",
        new=AsyncMock(side_effect=capture),
    ):
        await meta_get_performance_breakdown(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
            breakdown="hourly",
            level="adset",
        )
    assert captured["level"] == "adset"
    assert captured["breakdowns"] == "hourly_stats_aggregated_by_advertiser_time_zone"


@pytest.mark.integration
async def test_account_not_found_returns_error(db):
    from src.mcp.tools.meta_get_performance_breakdown import meta_get_performance_breakdown

    mid = uuid4()
    async with db.acquire() as conn:
        await managers.create(conn, manager_id=mid, email="t@v4company.com", full_name="T")

    result = await meta_get_performance_breakdown(
        manager_id=mid,
        session_id=uuid4(),
        ad_account_id="act_999999",
        breakdown="platform",
    )
    assert result["status"] == "error"
    assert "act_999999" in result["error_message"]
    assert "não encontrada" in result["error_message"]


@pytest.mark.integration
async def test_meta_api_error_returns_friendly_pt_br(db):
    from src.mcp.tools.meta_get_performance_breakdown import meta_get_performance_breakdown
    from src.meta_ads.errors import MetaAdsFriendlyError

    mid = await _seed(db)
    with patch(
        "src.mcp.tools.meta_get_performance_breakdown.run_meta_graph_get",
        new=AsyncMock(side_effect=MetaAdsFriendlyError("Limite Meta atingido.", retryable=True)),
    ):
        result = await meta_get_performance_breakdown(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
            breakdown="geo",
        )
    assert result["status"] == "error"
    assert "Limite Meta" in result["error_message"]
