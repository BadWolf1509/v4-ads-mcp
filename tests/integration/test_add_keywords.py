"""Integration tests for add_keywords (real Postgres, mocked SDK surface)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.db import connection
from src.mcp.context import McpRequestContext, clear_current, set_current
from tests.integration._seed import grant_google, seed_manager_with_session
from tests.unit.fixtures.fake_google_client import client_com_respostas


@pytest.fixture
async def session_ctx(db):
    pool = db
    async with pool.acquire() as conn:
        mid, sid, _ = await seed_manager_with_session(conn)
    # Seed google_ads_accounts + grant write access so ensure_account_access passes.
    async with pool.acquire() as conn:
        await grant_google(conn, mid, "1234567890")
    ctx = McpRequestContext(manager_id=mid, session_id=sid)
    set_current(ctx)
    yield ctx
    clear_current()


@pytest.mark.integration
async def test_add_keywords_full_cycle_audits(db, session_ctx):
    """3 KWs (2 added, 1 CRITERION_EXISTS) → run_mutation called with partial_failure → audit row with custom params_summary."""
    from src.mcp.tools.add_keywords import add_keywords

    fake_client = client_com_respostas([None, "CRITERION_EXISTS: keyword already exists", None])

    with (
        patch(
            "src.google_ads.mutations.build_client_for_manager", AsyncMock(return_value=fake_client)
        ),
        patch(
            "src.google_ads.mutations.get_builder",
            return_value=lambda c, cid, p: [MagicMock(), MagicMock(), MagicMock()],
        ),
        patch("src.google_ads.mutations.get_request_id", return_value="req-add-kw"),
    ):
        result = await add_keywords(
            {
                "customer_id": "1234567890",
                "ad_group_id": "111",
                "keywords": [
                    {"text": "kw alpha", "match_type": "EXACT", "cpc_bid_micros": 2000000},
                    {"text": "kw beta", "match_type": "PHRASE"},
                    {"text": "kw gamma", "match_type": "EXACT"},
                ],
            }
        )

    assert result["status"] == "applied"
    assert result["applied_count"] == 2  # 2 added, 1 already_exists
    assert result["added"][0]["status"] == "added"
    assert result["added"][1]["status"] == "already_exists"
    assert result["added"][2]["status"] == "added"

    # Verify audit_log row has the custom params_summary
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT operation, target_count, params_summary, provider_request_id "
            "FROM audit_log WHERE operation = 'add_keywords'"
        )
    assert len(rows) == 1
    assert rows[0]["target_count"] == 3
    assert rows[0]["provider_request_id"] == "req-add-kw"
    summary = rows[0]["params_summary"]
    summary_d = json.loads(summary) if isinstance(summary, str) else summary
    assert summary_d == {
        "ad_group_id": "111",
        "match_types_distribution": {"EXACT": 2, "PHRASE": 1},
        "with_custom_bid_count": 1,
        # R1-I2: o executor acrescenta a chave reservada `resultado`
        # (o que ACONTECEU) ao lado do resumo que a tool monta.
        "resultado": {
            "tentadas": 3,
            "aplicadas": 2,
            "mudaram": 2,
            "falharam": 1,
            "indices_com_falha": [1],
        },
    }
    # Critical: raw keyword texts NOT in audit
    assert "alpha" not in json.dumps(summary_d)
    assert "beta" not in json.dumps(summary_d)
