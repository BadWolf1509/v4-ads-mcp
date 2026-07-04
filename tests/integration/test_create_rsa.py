"""Integration tests for create_rsa (Sprint 3b.16).

Tests the full cycle:
  create_rsa(args) → dry_run + token → apply_change(token) → run_mutation
  → builder dispatch → applied response with resource_names (F13 assertion).

Pre-flight (validate_parent_ad_groups_for_rsa_create) is mocked to
return None (happy path) per CLAUDE.md "Pre-flight test convention
(post-Sprint 3b.8)" — avoids NoOAuthConnectionError in CI.

FIRST integration test asserting F13 (Sprint 3b.15) resource_names
extraction in real test context.
"""

from __future__ import annotations

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


def _client_with_rsa_response(resource_name: str) -> MagicMock:
    """Mock SDK client whose mutate() returns a response with one successful
    ad_group_ad_result containing the given resource_name.

    Mirrors test_create_ad_group.py pattern but adapted for RSA:
    - WhichOneof returns "ad_group_ad_result" (AdGroupAd oneof field name)
    - result_proto.resource_name returns the expected compound path
    """
    client = MagicMock()

    # Build the per-op response mock with resource_name accessible via attribute.
    op_resp = MagicMock()
    result_proto = MagicMock()
    result_proto.resource_name = resource_name

    # WhichOneof("response") returns the oneof field name set for this op.
    # For AdGroupAd (RSA) creates, the field is "ad_group_ad_result".
    op_resp._pb.WhichOneof = MagicMock(return_value="ad_group_ad_result")
    op_resp._pb.ad_group_ad_result = result_proto

    response = MagicMock()
    response.mutate_operation_responses = [op_resp]

    # create_rsa does NOT use partial_failure — always all-or-nothing.
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
async def test_create_rsa_full_cycle_audits(db, session_ctx) -> None:
    """create_rsa → dry_run + token → apply_change consumes token →
    run_mutation dispatched → applied response with resource_names (F13)
    + audit_log row with custom params_summary.

    FIRST integration test asserting F13 (Sprint 3b.15) resource_names
    extraction — validates that mutations.py correctly propagates
    resource_names from mock mutate_operation_responses through apply_change
    to the final tool response.
    """
    from src.mcp.tools.apply_change import apply_change
    from src.mcp.tools.create_rsa import create_rsa

    # RSA resource_name is compound: customers/{cid}/adGroupAds/{ag_id}~{ad_id}
    expected_resource_name = "customers/1234567890/adGroupAds/100~111"
    fake_client = _client_with_rsa_response(expected_resource_name)

    # CRITICAL (Sprint 3b.11 lesson): mock pre-flight to skip real OAuth calls.
    # Patch site is the tool module namespace, NOT _common.py namespace.
    with (
        patch(
            "src.mcp.tools.create_rsa.validate_parent_ad_groups_for_rsa_create",
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
            return_value="req-create-rsa",
        ),
    ):
        # Step 1: Tool returns dry_run + confirmation token.
        dry_run_result = await create_rsa(
            {
                "customer_id": "1234567890",
                "rsas": [
                    {
                        "ad_group_id": "100",
                        "headlines": [
                            "Headline One",
                            "Headline Two",
                            "Headline Three",
                            "Headline Four",
                            "Headline Five",
                        ],
                        "descriptions": [
                            "Description one longer text here",
                            "Description two another text",
                        ],
                        "final_urls": ["https://example.com/"],
                    }
                ],
            }
        )

        assert dry_run_result["status"] == "dry_run"
        assert dry_run_result["operation"] == "create_rsa"
        token = dry_run_result["confirmation_token"]
        assert token

        # Step 2: apply_change consumes token → dispatches run_mutation.
        apply_result = await apply_change({"confirmation_token": token})

    assert apply_result["status"] == "applied"
    assert apply_result["operation"] == "create_rsa"
    assert apply_result["applied_count"] == 1
    assert apply_result["provider_request_id"] == "req-create-rsa"

    # F13 (Sprint 3b.15) — FIRST integration test asserting resource_names.
    # Validates that mutations.py extracts resource_name from the mocked
    # mutate_operation_responses and propagates it through apply_change.
    assert "resource_names" in apply_result
    assert isinstance(apply_result["resource_names"], list)
    assert len(apply_result["resource_names"]) == apply_result["applied_count"]
    assert apply_result["resource_names"][0] == expected_resource_name

    # Step 3: Verify audit_log row has expected target_count + provider_request_id
    # + custom params_summary (counts only — no ad copy text per spec §3.6).
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT operation, target_count, params_summary, provider_request_id "
            "FROM audit_log WHERE operation = 'create_rsa'"
        )
    assert len(rows) == 1
    assert rows[0]["target_count"] == 1
    assert rows[0]["provider_request_id"] == "req-create-rsa"
    summary = rows[0]["params_summary"]
    summary_d = json.loads(summary) if isinstance(summary, str) else summary
    assert summary_d == {
        "count": 1,
        "status_distribution": {"PAUSED": 1},
        "avg_headlines": 5.0,
        "avg_descriptions": 2.0,
        "with_path1": 0,
        "with_path2": 0,
        "unique_parent_ad_groups": 1,
    }
    # Critical: ad copy text NOT in audit (privacy-safe summary per spec §3.6).
    assert "Headline One" not in json.dumps(summary_d)
    assert "Description one" not in json.dumps(summary_d)
