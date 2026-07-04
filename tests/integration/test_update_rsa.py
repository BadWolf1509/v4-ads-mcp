"""Integration tests for update_rsa (Sprint 3b.18).

Tests the full cycle:
  update_rsa(args) → dry_run + token → apply_change(token) → run_mutation
  → builder dispatch → applied response with resource_names (F13 assertion).

Pre-flight (validate_existing_rsas_for_update) is mocked to return None
(happy path) per CLAUDE.md "Pre-flight test convention (post-Sprint 3b.8)"
— avoids NoOAuthConnectionError in CI.

KEY DIFFERENCE from create_rsa integration test: mock uses 'ad_result'
oneof (not 'ad_group_ad_result') because update_rsa uses
MutateOperation.ad_operation (top-level Ad mutation via AdService).
Resource_name format: customers/X/ads/Y (not compound ~-separated).
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


def _client_with_ad_response(resource_name: str) -> MagicMock:
    """Mock SDK client whose mutate() returns a response with one successful
    ad_result containing the given resource_name.

    KEY DIFFERENCE from create_rsa: WhichOneof returns "ad_result" (not
    "ad_group_ad_result") because update_rsa uses MutateOperation.ad_operation
    (top-level Ad mutation via AdService). Resource_name format is flat:
    customers/{cid}/ads/{ad_id} — no compound ~-separator.
    """
    client = MagicMock()

    # Build the per-op response mock with resource_name accessible via attribute.
    op_resp = MagicMock()
    result_proto = MagicMock()
    result_proto.resource_name = resource_name

    # WhichOneof("response") returns the oneof field name set for this op.
    # For top-level Ad mutations (update_rsa), the field is "ad_result".
    op_resp._pb.WhichOneof = MagicMock(return_value="ad_result")
    op_resp._pb.ad_result = result_proto

    response = MagicMock()
    response.mutate_operation_responses = [op_resp]

    # update_rsa does NOT use partial_failure — always all-or-nothing.
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
async def test_update_rsa_full_cycle_audits(db, session_ctx) -> None:
    """update_rsa → dry_run + token → apply_change consumes token →
    run_mutation dispatched → applied response with resource_names (F13)
    + audit_log row with custom params_summary.

    Verifies F13 (Sprint 3b.15) resource_names extraction with ad_result
    oneof — top-level Ad path format (customers/X/ads/Y), not compound.
    """
    from src.mcp.tools.apply_change import apply_change
    from src.mcp.tools.update_rsa import update_rsa

    # update_rsa resource_name is flat: customers/{cid}/ads/{ad_id}
    expected_resource_name = "customers/1234567890/ads/100"
    fake_client = _client_with_ad_response(expected_resource_name)

    # CRITICAL (Sprint 3b.11 lesson): mock pre-flight to skip real OAuth calls.
    # Patch site is the tool module namespace, NOT _common.py namespace.
    with (
        patch(
            "src.mcp.tools.update_rsa.validate_existing_rsas_for_update",
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
            return_value="req-update-rsa",
        ),
    ):
        # Step 1: Tool returns dry_run + confirmation token.
        dry_run_result = await update_rsa(
            {
                "customer_id": "1234567890",
                "updates": [
                    {
                        "ad_id": "100",
                        "headlines": [
                            "Headline One",
                            "Headline Two",
                            "Headline Three",
                        ],
                    }
                ],
            }
        )

        assert dry_run_result["status"] == "dry_run"
        assert dry_run_result["operation"] == "update_rsa"
        token = dry_run_result["confirmation_token"]
        assert token

        # Step 2: apply_change consumes token → dispatches run_mutation.
        apply_result = await apply_change({"confirmation_token": token})

    assert apply_result["status"] == "applied"
    assert apply_result["operation"] == "update_rsa"
    assert apply_result["applied_count"] == 1
    assert apply_result["provider_request_id"] == "req-update-rsa"

    # F13 (Sprint 3b.15) — resource_names extraction with ad_result oneof.
    # Validates top-level Ad path format (no compound ~-separator).
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
            "FROM audit_log WHERE operation = 'update_rsa'"
        )
    assert len(rows) == 1
    assert rows[0]["target_count"] == 1
    assert rows[0]["provider_request_id"] == "req-update-rsa"
    summary = rows[0]["params_summary"]
    summary_d = json.loads(summary) if isinstance(summary, str) else summary
    assert summary_d == {
        "count": 1,
        "fields_updated_distribution": {"headlines": 1},
        "unique_ads": 1,
    }
    # Critical: ad copy text NOT in audit (privacy-safe summary per spec §3.6).
    assert "Headline One" not in json.dumps(summary_d)
