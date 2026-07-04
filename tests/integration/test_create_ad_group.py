"""Integration tests for create_ad_group (real Postgres, mocked SDK surface).

Tests the full cycle:
  create_ad_group(args) → dry_run + token → apply_change(token) → run_mutation
  → builder dispatch → audit_log row with custom params_summary.

Pre-flight (validate_parent_campaigns_for_ad_group_create) is mocked to
return None (happy path) per CLAUDE.md "Pre-flight test convention
(post-Sprint 3b.8)" — avoids NoOAuthConnectionError in CI.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.db import connection
from src.db.repositories import google_ads_accounts, manager_account_access, managers, mcp_sessions
from src.mcp.context import McpRequestContext, clear_current, set_current

pytestmark = pytest.mark.integration


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


def _client_with_responses(per_op_errors):
    """Mock SDK client whose mutate() returns response with per-op statuses.

    Mirrors Sprint 3b.1/3b.6 test pattern. Each entry: None = success,
    string = error message.
    """
    client = MagicMock()
    fake_responses = []
    for err in per_op_errors:
        r = MagicMock()
        if err is None:
            r._pb.WhichOneof = MagicMock(return_value="ad_group_result")
        else:
            r._pb.WhichOneof = MagicMock(return_value=None)
        fake_responses.append(r)

    response = MagicMock()
    response.mutate_operation_responses = fake_responses

    # create_ad_group does NOT use partial_failure — always all-or-nothing.
    response.partial_failure_error.code = 0
    response.partial_failure_error.details = []

    fake_service = MagicMock()
    fake_service.mutate = MagicMock(return_value=response)
    client.get_service = MagicMock(return_value=fake_service)

    failure_type_stub = MagicMock()
    failure_type_stub._meta.pb = lambda: MagicMock(errors=[])

    def get_type(name):
        if name == "GoogleAdsFailure":
            return failure_type_stub
        return MagicMock(
            mutate_operations=[],
            partial_failure_mode=MagicMock(),
        )

    client.get_type = MagicMock(side_effect=get_type)
    client.enums.PartialFailureModeEnum.PARTIAL_FAILURE = "PARTIAL_FAILURE"
    return client


@pytest.mark.integration
async def test_create_ad_group_full_cycle_audits(db, session_ctx) -> None:
    """create_ad_group → dry_run + token → apply_change consumes token →
    run_mutation dispatched → applied response + audit_log row with
    custom params_summary.
    """
    from src.mcp.tools.apply_change import apply_change
    from src.mcp.tools.create_ad_group import create_ad_group

    fake_client = _client_with_responses([None])

    # CRITICAL (Sprint 3b.11 lesson): mock pre-flight to skip real OAuth calls.
    with (
        patch(
            "src.mcp.tools.create_ad_group.validate_parent_campaigns_for_ad_group_create",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.google_ads.mutations.build_client_for_manager",
            AsyncMock(return_value=fake_client),
        ),
        patch(
            "src.google_ads.mutations.get_builder",
            return_value=lambda c, cid, p: [MagicMock()],
        ),
        patch(
            "src.google_ads.mutations.get_request_id",
            return_value="req-create-ag",
        ),
    ):
        # Step 1: Tool returns dry_run + confirmation token.
        dry_run_result = await create_ad_group(
            {
                "customer_id": "1234567890",
                "ad_groups": [
                    {"campaign_id": "100", "name": "Test AG"},
                ],
            }
        )

        assert dry_run_result["status"] == "dry_run"
        assert dry_run_result["operation"] == "create_ad_group"
        token = dry_run_result["confirmation_token"]
        assert token

        # Step 2: apply_change consumes token → dispatches run_mutation.
        apply_result = await apply_change({"confirmation_token": token})

    assert apply_result["status"] == "applied"
    assert apply_result["operation"] == "create_ad_group"
    assert apply_result["applied_count"] == 1
    assert apply_result["provider_request_id"] == "req-create-ag"
    # F13: resource_names propagated from run_mutation through apply_change
    assert "resource_names" in apply_result
    assert isinstance(apply_result["resource_names"], list)
    assert len(apply_result["resource_names"]) == apply_result["applied_count"]

    # Step 3: Verify audit_log row has expected target_count + provider_request_id
    # + custom params_summary (names excluded, only distribution counts).
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT operation, target_count, params_summary, provider_request_id "
            "FROM audit_log WHERE operation = 'create_ad_group'"
        )
    assert len(rows) == 1
    assert rows[0]["target_count"] == 1
    assert rows[0]["provider_request_id"] == "req-create-ag"
    summary = rows[0]["params_summary"]
    summary_d = json.loads(summary) if isinstance(summary, str) else summary
    assert summary_d == {
        "count": 1,
        "type_distribution": {"SEARCH_STANDARD": 1},
        "status_distribution": {"PAUSED": 1},
        "with_custom_bid_count": 0,
        "unique_parent_campaigns": 1,
    }
    # Critical: ad_group names NOT in audit (privacy-safe summary).
    assert "Test AG" not in json.dumps(summary_d)
