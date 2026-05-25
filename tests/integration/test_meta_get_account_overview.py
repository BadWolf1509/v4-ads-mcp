"""Integration tests Sprint M.2b: meta_get_account_overview tool."""

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
        await manager_meta_account_access.grant(
            conn,
            manager_id=mid,
            ad_account_id="act_123456",
        )
    return mid


@pytest.mark.integration
async def test_meta_get_account_overview_happy_path(db):
    """Happy path: 2 graph calls + parse + deltas + warnings empty + return shape."""
    from src.mcp.tools.meta_get_account_overview import meta_get_account_overview

    mid = await _seed_manager_with_meta_conn(db)

    current_body = {
        "data": [
            {
                "spend": "1200.0",
                "impressions": "10000",
                "clicks": "300",
                "ctr": "3.0",
                "cpc": "4.0",
                "reach": "8000",
                "frequency": "1.25",
                "actions": [{"action_type": "purchase", "value": "40"}],
                "action_values": [{"action_type": "purchase", "value": "8000"}],
                "purchase_roas": [{"action_type": "omni_purchase", "value": "6.67"}],
            }
        ]
    }
    previous_body = {
        "data": [
            {
                "spend": "1000.0",
                "impressions": "8000",
                "clicks": "240",
                "ctr": "3.0",
                "cpc": "4.17",
                "reach": "6500",
                "frequency": "1.23",
                "actions": [{"action_type": "purchase", "value": "30"}],
                "action_values": [{"action_type": "purchase", "value": "6000"}],
                "purchase_roas": [{"action_type": "omni_purchase", "value": "6.0"}],
            }
        ]
    }

    with patch(
        "src.mcp.tools.meta_get_account_overview.run_meta_graph_get",
        new=AsyncMock(side_effect=[current_body, previous_body]),
    ):
        result = await meta_get_account_overview(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
            date_range="LAST_7_DAYS",
        )

    assert result["status"] == "success"
    assert result["ad_account_id"] == "act_123456"
    assert result["account_name"] == "Test Account"
    assert result["account_status_label"] == "ATIVO"
    assert result["currency"] == "BRL"
    assert result["current"]["spend"] == 1200.0
    assert result["current"]["conversions"] == 40
    assert result["current"]["purchase_roas"] == 6.67
    assert result["previous"]["spend"] == 1000.0
    assert result["deltas"]["spend_pct"] == 20.0
    assert result["deltas"]["conversions_pct"] == round((40 - 30) / 30 * 100, 2)
    assert result["_warnings"] == []
    assert "date_range" in result
    assert result["date_range"]["start"] is not None
    assert result["date_range"]["end"] is not None


@pytest.mark.integration
async def test_meta_get_account_overview_account_status_warning(db):
    """account_status=PAGAMENTO_PENDENTE → _warnings list populated."""
    from src.mcp.tools.meta_get_account_overview import meta_get_account_overview

    mid = await _seed_manager_with_meta_conn(db, account_status=3)

    body = {"data": [{"spend": "100"}]}
    with patch(
        "src.mcp.tools.meta_get_account_overview.run_meta_graph_get",
        new=AsyncMock(side_effect=[body, body]),
    ):
        result = await meta_get_account_overview(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
        )

    assert result["status"] == "success"
    assert result["account_status_label"] == "PAGAMENTO_PENDENTE"
    assert any("PAGAMENTO_PENDENTE" in w for w in result["_warnings"])


@pytest.mark.integration
async def test_meta_get_account_overview_token_expiring_warning(db):
    """token_expires_at em 5d → _warnings list populated."""
    from src.mcp.tools.meta_get_account_overview import meta_get_account_overview

    mid = await _seed_manager_with_meta_conn(db, token_expires_in_days=5)

    body = {"data": [{"spend": "100"}]}
    with patch(
        "src.mcp.tools.meta_get_account_overview.run_meta_graph_get",
        new=AsyncMock(side_effect=[body, body]),
    ):
        result = await meta_get_account_overview(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
        )

    assert result["status"] == "success"
    assert any("Token OAuth Meta expira" in w and "dias" in w for w in result["_warnings"])


@pytest.mark.integration
async def test_meta_get_account_overview_no_oc_returns_error(db):
    """Manager sem conexão Meta active → error PT-BR friendly."""
    from src.mcp.tools.meta_get_account_overview import meta_get_account_overview

    mid = uuid4()
    async with db.acquire() as conn:
        await managers.create(conn, manager_id=mid, email="t@v4company.com", full_name="Tester")
        await meta_ad_accounts.upsert_many(
            conn,
            [
                {
                    "ad_account_id": "act_123456",
                    "business_id": "bm",
                    "business_name": "BM",
                    "account_name": "AC",
                    "currency": "BRL",
                    "timezone_name": "America/Sao_Paulo",
                    "account_status": 1,
                }
            ],
        )

    result = await meta_get_account_overview(
        manager_id=mid,
        session_id=uuid4(),
        ad_account_id="act_123456",
    )

    assert result["status"] == "error"
    assert "Nenhuma conexão Meta ativa" in result["error_message"]
