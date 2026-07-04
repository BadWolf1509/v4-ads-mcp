"""Integration tests for add_negative_keywords."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.db.repositories import google_ads_accounts, manager_account_access, managers, mcp_sessions
from src.mcp.context import McpRequestContext, clear_current, set_current


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
    # Seed google_ads_accounts + grant write access so ensure_account_access passes.
    async with pool.acquire() as conn:
        await google_ads_accounts.upsert_many(
            conn,
            [{"customer_id": "1234567890", "mcc_id": "0000000000", "descriptive_name": "Test"}],
        )
        await manager_account_access.grant(
            conn, manager_id=mid, customer_id="1234567890", access_level="write", granted_by=mid
        )
    ctx = McpRequestContext(manager_id=mid, session_id=sess.id)
    set_current(ctx)
    yield ctx
    clear_current()


def _fake_client():
    fc = MagicMock()
    fs = MagicMock()
    fr = MagicMock()
    fs.mutate = MagicMock(return_value=fr)
    fc.get_service = MagicMock(return_value=fs)
    fc.get_type = MagicMock(return_value=MagicMock(mutate_operations=[]))
    return fc


@pytest.mark.integration
async def test_add_negative_keywords_auto_applies_single(db, session_ctx):
    from src.mcp.tools.add_negative_keywords import add_negative_keywords

    with (
        patch(
            "src.google_ads.mutations.build_client_for_manager",
            AsyncMock(return_value=_fake_client()),
        ),
        patch(
            "src.google_ads.mutations.get_builder",
            return_value=lambda c, cid, p: [MagicMock()],
        ),
        patch(
            "src.google_ads.mutations.get_request_id",
            return_value="req-neg",
        ),
    ):
        result = await add_negative_keywords(
            {
                "customer_id": "1234567890",
                "campaign_id": "111",
                "keywords": [{"text": "free", "match_type": "BROAD"}],
            }
        )

    assert result["status"] == "applied"
    assert result["applied_count"] == 1


@pytest.mark.integration
async def test_add_negative_keywords_auto_applies_bulk(db, session_ctx):
    """Even 100+ negatives auto-apply (spec §7.1: negatives are safe)."""
    from src.mcp.tools.add_negative_keywords import add_negative_keywords

    keywords = [{"text": f"junk-{i}", "match_type": "EXACT"} for i in range(100)]

    with (
        patch(
            "src.google_ads.mutations.build_client_for_manager",
            AsyncMock(return_value=_fake_client()),
        ),
        patch(
            "src.google_ads.mutations.get_builder",
            return_value=lambda c, cid, p: [MagicMock() for _ in range(100)],
        ),
        patch(
            "src.google_ads.mutations.get_request_id",
            return_value="req-neg",
        ),
    ):
        result = await add_negative_keywords(
            {
                "customer_id": "1234567890",
                "campaign_id": "111",
                "keywords": keywords,
            }
        )

    assert result["status"] == "applied"
    assert result["applied_count"] == 100


@pytest.mark.integration
async def test_add_negative_keywords_summary_lists_match_types(db, session_ctx):
    from src.mcp.tools.add_negative_keywords import add_negative_keywords

    with (
        patch(
            "src.google_ads.mutations.build_client_for_manager",
            AsyncMock(return_value=_fake_client()),
        ),
        patch(
            "src.google_ads.mutations.get_builder",
            return_value=lambda c, cid, p: [MagicMock(), MagicMock()],
        ),
        patch(
            "src.google_ads.mutations.get_request_id",
            return_value="req-neg",
        ),
    ):
        result = await add_negative_keywords(
            {
                "customer_id": "1234567890",
                "campaign_id": "111",
                "keywords": [
                    {"text": "free", "match_type": "BROAD"},
                    {"text": "barato", "match_type": "PHRASE"},
                ],
            }
        )

    assert "BROAD" in result["blast_summary"]
    assert "PHRASE" in result["blast_summary"]


@pytest.mark.integration
async def test_remove_negative_keywords_auto_applies_single(db, session_ctx):
    from src.mcp.tools.remove_negative_keywords import remove_negative_keywords

    with (
        patch(
            "src.google_ads.mutations.build_client_for_manager",
            AsyncMock(return_value=_fake_client()),
        ),
        patch(
            "src.google_ads.mutations.get_builder",
            return_value=lambda c, cid, p: [MagicMock()],
        ),
        patch(
            "src.google_ads.mutations.get_request_id",
            return_value="req-neg",
        ),
    ):
        result = await remove_negative_keywords(
            {
                "customer_id": "1234567890",
                "campaign_id": "111",
                "criterion_ids": ["222333"],
            }
        )

    assert result["status"] == "applied"
    assert result["applied_count"] == 1


@pytest.mark.integration
async def test_remove_negative_keywords_auto_applies_bulk(db, session_ctx):
    """Even 100 criterion removals auto-apply (spec §7.1: negatives are safe)."""
    from src.mcp.tools.remove_negative_keywords import remove_negative_keywords

    criterion_ids = [str(i) for i in range(100)]

    with (
        patch(
            "src.google_ads.mutations.build_client_for_manager",
            AsyncMock(return_value=_fake_client()),
        ),
        patch(
            "src.google_ads.mutations.get_builder",
            return_value=lambda c, cid, p: [MagicMock() for _ in range(100)],
        ),
        patch(
            "src.google_ads.mutations.get_request_id",
            return_value="req-neg",
        ),
    ):
        result = await remove_negative_keywords(
            {
                "customer_id": "1234567890",
                "campaign_id": "111",
                "criterion_ids": criterion_ids,
            }
        )

    assert result["status"] == "applied"
    assert result["applied_count"] == 100
