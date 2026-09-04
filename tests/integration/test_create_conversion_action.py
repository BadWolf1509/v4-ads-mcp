"""Integration test: create_conversion_action full cycle (Sprint 3b.19A).

Tests dry_run → apply_change → builder runs → applied response with
resource_names matching mocked ConversionAction ID. F13 cross-cutting
(Sprint 3b.15) auto-inherited via run_mutation — validates ConversionAction
(third resource type after AdGroup/Ad) also returns resource_names correctly.

Mocks validate_conversion_action_create per Sprint 3b.11 "Pre-flight test
convention" — helper's run_report import lives in _common.py namespace,
NOT in the tool's namespace. Patch at tool module namespace to bypass real
OAuth calls in CI.
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


def _client_with_conversion_action_response(resource_name: str) -> MagicMock:
    """Mock SDK client whose mutate() returns a response with one successful
    conversion_action_result containing the given resource_name.

    Mirrors test_create_rsa.py pattern but adapted for ConversionAction:
    - WhichOneof returns "conversion_action_result" (ConversionAction oneof field name)
    - result_proto.resource_name returns the expected customer-level path
    """
    client = MagicMock()

    # Build the per-op response mock with resource_name accessible via attribute.
    op_resp = MagicMock()
    result_proto = MagicMock()
    result_proto.resource_name = resource_name

    # WhichOneof("response") returns the oneof field name set for this op.
    # For ConversionAction creates, the field is "conversion_action_result".
    op_resp._pb.WhichOneof = MagicMock(return_value="conversion_action_result")
    op_resp._pb.conversion_action_result = result_proto

    response = MagicMock()
    response.mutate_operation_responses = [op_resp]

    # create_conversion_action does NOT use partial_failure — always all-or-nothing.
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
async def test_create_conversion_action_full_cycle_audits(db, session_ctx) -> None:
    """create_conversion_action → dry_run + token → apply_change consumes token →
    run_mutation dispatched → applied response with resource_names (F13)
    + audit_log row with custom params_summary.

    F13 (Sprint 3b.15) THIRD integration test asserting resource_names extraction
    — validates ConversionAction resource path (customers/{cid}/conversionActions/{id})
    flows correctly through run_mutation → apply_change → tool response.
    Prior F13 validations: Sprint 3b.16 (AdGroupAd via ad_group_ad_operation),
    Sprint 3b.18 (Ad via ad_operation). This is conversion_action_operation.
    """
    from src.mcp.tools.apply_change import apply_change
    from src.mcp.tools.create_conversion_action import create_conversion_action

    # ConversionAction resource_name is customer-level: customers/{cid}/conversionActions/{id}
    expected_resource_name = "customers/1234567890/conversionActions/9876543210"
    fake_client = _client_with_conversion_action_response(expected_resource_name)

    # CRITICAL (Sprint 3b.11 lesson): mock pre-flight to skip real OAuth calls.
    # Patch site is the tool module namespace, NOT _common.py namespace.
    with (
        patch(
            "src.mcp.tools.create_conversion_action.validate_conversion_action_create",
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
            return_value="req-create-ca",
        ),
    ):
        # Step 1: Tool returns dry_run + confirmation token.
        dry_run_result = await create_conversion_action(
            {
                "customer_id": "1234567890",
                "conversion_actions": [
                    {"name": "Test Lead Int", "category": "SUBMIT_LEAD_FORM", "type": "WEBPAGE"}
                ],
            }
        )

        assert dry_run_result["status"] == "dry_run"
        assert dry_run_result["operation"] == "create_conversion_action"
        token = dry_run_result["confirmation_token"]
        assert token

        # Step 2: apply_change consumes token → dispatches run_mutation.
        apply_result = await apply_change({"confirmation_token": token})

    assert apply_result["status"] == "applied"
    assert apply_result["operation"] == "create_conversion_action"
    assert apply_result["applied_count"] == 1
    assert apply_result["provider_request_id"] == "req-create-ca"

    # F13 (Sprint 3b.15) — validates resource_names propagation for ConversionAction.
    # Third resource type exercising F13 cross-cutting (AdGroup → Ad → ConversionAction).
    assert "resource_names" in apply_result
    assert isinstance(apply_result["resource_names"], list)
    assert len(apply_result["resource_names"]) == apply_result["applied_count"]
    assert apply_result["resource_names"][0] == expected_resource_name

    # Step 3: Verify audit_log row has expected target_count + provider_request_id
    # + custom params_summary (counts only — no action names per spec §3.6).
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT operation, target_count, params_summary, provider_request_id "
            "FROM audit_log WHERE operation = 'create_conversion_action' AND dry_run IS NOT TRUE"
        )
    assert len(rows) == 1, "a consulta filtra dry_run; so a linha APLICADA conta"

    # F148: o preview tambem deixa rastro, com a contagem PLANEJADA e
    # `dry_run=true`. Antes do fix esta linha nao existia e o fluxo inteiro
    # aparecia na trilha como uma unica escrita, a aplicada.
    async with pool.acquire() as conn:
        previews = await conn.fetch(
            "SELECT action_type, target_count, dry_run FROM audit_log "
            "WHERE operation = 'create_conversion_action' AND dry_run IS TRUE"
        )
    assert len(previews) == 1, "o dry-run tem que deixar exatamente uma linha"
    assert previews[0]["action_type"] == "mutate"
    assert previews[0]["target_count"] is not None, (
        "target_count NULL significa que a tool nao declarou __target_count__"
    )
    assert rows[0]["target_count"] == 1
    assert rows[0]["provider_request_id"] == "req-create-ca"
    summary = rows[0]["params_summary"]
    summary_d = json.loads(summary) if isinstance(summary, str) else summary
    assert summary_d == {
        "count": 1,
        "categories": {"SUBMIT_LEAD_FORM": 1},
        "types": {"WEBPAGE": 1},
        "with_default_value": 0,
        "with_always_use_default": 0,
    }
    # Critical: action names NOT in audit (privacy-safe summary per spec §3.6).
    assert "Test Lead Int" not in json.dumps(summary_d)
