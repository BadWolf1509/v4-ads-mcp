"""Integration tests Sprint M.3 Task 4: meta_get_ad_set_performance."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.db.repositories import (
    manager_meta_account_access,
    managers,
    meta_ad_accounts,
    meta_oauth_connections,
)

pytestmark = pytest.mark.asyncio


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
async def test_happy_path_returns_adset_rows_sorted(db):
    """2 ad sets retornados → ordenados por spend_brl DESC.

    F89: os mocks não carregam mais `billing_event`/`daily_budget`/
    `effective_status`. A Meta Insights nunca os devolve (metadata de /adsets —
    F54), então mock que os incluía descrevia uma resposta impossível — e foi
    parte de por que o parser seguiu lendo campo morto por sprints.
    """
    from src.mcp.tools.meta_get_ad_set_performance import meta_get_ad_set_performance

    mid = await _seed_manager_with_meta_conn(db)

    body = {
        "data": [
            {
                "adset_id": "as1",
                "adset_name": "AS Low",
                "campaign_id": "c1",
                "campaign_name": "Camp 1",
                "optimization_goal": "OFFSITE_CONVERSIONS",
                "spend": "200",
                "actions": [{"action_type": "purchase", "value": "2"}],
            },
            {
                "adset_id": "as2",
                "adset_name": "AS High",
                "campaign_id": "c1",
                "campaign_name": "Camp 1",
                "optimization_goal": "OFFSITE_CONVERSIONS",
                "spend": "1500",
                "actions": [{"action_type": "purchase", "value": "30"}],
            },
        ]
    }

    with patch(
        "src.mcp.tools._meta_performance.run_meta_graph_get",
        new=AsyncMock(return_value=body),
    ):
        result = await meta_get_ad_set_performance(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
        )

    assert result["status"] == "success"
    assert result["total_rows"] == 2
    assert result["rows"][0]["ad_set_name"] == "AS High"
    assert result["rows"][0]["spend_brl"] == 1500.0
    assert result["rows"][0]["optimization_goal"] == "OFFSITE_CONVERSIONS"
    assert result["rows"][1]["ad_set_name"] == "AS Low"
    # F89: metadata de entidade não sai na resposta — antes vinha None sempre.
    assert "daily_budget_brl" not in result["rows"][0]
    assert "billing_event" not in result["rows"][0]


@pytest.mark.integration
async def test_metadata_de_orcamento_nunca_vaza_pra_resposta(db):
    """F89 — teste REESCRITO. Era `test_cbo_adset_no_daily_budget_returns_none`.

    O antigo dizia cobrir o caso CBO (ad set sem orçamento próprio → None), mas a
    F54 tirou `daily_budget` da query: TODO ad set vinha None, CBO ou não. A
    distinção que ele supunha testar não existia. Agora garantimos que metadata
    não pedida não é repassada, mesmo se a Meta a mandar.
    """
    from src.mcp.tools.meta_get_ad_set_performance import meta_get_ad_set_performance

    mid = await _seed_manager_with_meta_conn(db)

    body = {
        "data": [
            {
                "adset_id": "as1",
                "adset_name": "CBO AS",
                "campaign_id": "c1",
                "campaign_name": "CBO Camp",
                "effective_status": "ACTIVE",  # não pedido — não pode sair
                "daily_budget": "5000",  # idem
                "spend": "100",
            }
        ]
    }

    with patch(
        "src.mcp.tools._meta_performance.run_meta_graph_get",
        new=AsyncMock(return_value=body),
    ):
        result = await meta_get_ad_set_performance(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
        )

    row = result["rows"][0]
    assert row["ad_set_name"] == "CBO AS"
    assert "daily_budget_brl" not in row
    assert "effective_status" not in row


@pytest.mark.integration
async def test_level_adset_in_params(db):
    """Confirma level='adset' passado à Graph API."""
    from src.mcp.tools.meta_get_ad_set_performance import meta_get_ad_set_performance

    mid = await _seed_manager_with_meta_conn(db)

    captured_params: dict = {}

    async def capture_call(**kwargs):
        captured_params.update(kwargs["params"])
        return {"data": []}

    with patch(
        "src.mcp.tools._meta_performance.run_meta_graph_get",
        new=AsyncMock(side_effect=capture_call),
    ):
        await meta_get_ad_set_performance(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
        )

    assert captured_params["level"] == "adset"
    assert "adset_id" in captured_params["fields"]
    assert "optimization_goal" in captured_params["fields"]


@pytest.mark.integration
async def test_account_not_found_returns_error(db):
    """ad_account_id inexistente → error PT-BR."""
    from src.mcp.tools.meta_get_ad_set_performance import meta_get_ad_set_performance

    mid = uuid4()
    async with db.acquire() as conn:
        await managers.create(conn, manager_id=mid, email="t@v4company.com", full_name="Tester")

    result = await meta_get_ad_set_performance(
        manager_id=mid,
        session_id=uuid4(),
        ad_account_id="act_999999",
    )

    assert result["status"] == "error"
    assert "act_999999" in result["error_message"]
