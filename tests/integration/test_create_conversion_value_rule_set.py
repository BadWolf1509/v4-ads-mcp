"""Integration test: create_conversion_value_rule_set full cycle (Sprint 3b.19B).

Tests dry_run → apply_change → builder runs chained mutation → applied
response with 3 resource_names (2 rules + 1 set). First time F13 cross-
cutting tested em chained mutation case.

Mocks both pre-flight helpers at tool's module namespace per Sprint 3b.11
"Pre-flight test convention".
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


def _client_with_chained_response() -> MagicMock:
    """Mock SDK client returning 3 mutate_operation_responses (2 rules + 1 set).

    Mirrors test_create_conversion_action.py pattern adapted for chained mutation:
    - op[0]: conversion_value_rule_result  (rule 1)
    - op[1]: conversion_value_rule_result  (rule 2)
    - op[2]: conversion_value_rule_set_result  (the set)
    Each has a distinct resource_name to exercise F13 ordering.
    """
    client = MagicMock()

    paths = [
        "customers/1234567890/conversionValueRules/11111",
        "customers/1234567890/conversionValueRules/22222",
        "customers/1234567890/conversionValueRuleSets/99999",
    ]
    oneof_names = [
        "conversion_value_rule_result",
        "conversion_value_rule_result",
        "conversion_value_rule_set_result",
    ]

    op_responses = []
    for path, oneof_name in zip(paths, oneof_names, strict=True):
        op_resp = MagicMock()
        result_proto = MagicMock()
        result_proto.resource_name = path

        # WhichOneof("response") must return the oneof field name for this op.
        op_resp._pb.WhichOneof = MagicMock(return_value=oneof_name)
        setattr(op_resp._pb, oneof_name, result_proto)
        op_responses.append(op_resp)

    response = MagicMock()
    response.mutate_operation_responses = op_responses
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
async def test_create_conversion_value_rule_set_full_cycle_returns_3_resource_names(
    db, session_ctx
) -> None:
    """End-to-end: dry_run + token → apply_change consumes token →
    run_mutation dispatched → applied response with 3 resource_names (chained F13)
    + audit_log row with custom params_summary.

    F13 (Sprint 3b.15) FOURTH integration test asserting resource_names extraction
    — validates chained mutation case: N rule resource_names + 1 set resource_name,
    verifying ordering matches mock client's 3 mutate_operation_responses with
    two distinct oneof field names (conversion_value_rule_result ×2 +
    conversion_value_rule_set_result ×1).

    Prior F13 validations: Sprint 3b.16 (AdGroupAd via ad_group_ad_operation),
    Sprint 3b.18 (Ad via ad_operation), Sprint 3b.19A (ConversionAction via
    conversion_action_operation). This is the first chained (multi-resource-type)
    mutation exercising F13.
    """
    from src.mcp.tools.apply_change import apply_change
    from src.mcp.tools.create_conversion_value_rule_set import (
        create_conversion_value_rule_set,
    )

    fake_client = _client_with_chained_response()

    # CRITICAL (Sprint 3b.11 lesson): patch pre-flight at tool module namespace.
    # validate_campaign_for_value_rule_set is only called for CAMPAIGN attachment —
    # still patched defensively so geo-only test stays hermetic.
    # validate_geo_target_constants_br_only fires because we have a
    # GEO_LOCATION rule — must be mocked to skip real OAuth/GAQL call.
    with (
        patch(
            "src.mcp.tools.create_conversion_value_rule_set.validate_campaign_for_value_rule_set",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.mcp.tools.create_conversion_value_rule_set.validate_geo_target_constants_br_only",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.google_ads.mutations.build_client_for_manager",
            AsyncMock(return_value=fake_client),
        ),
        patch(
            "src.google_ads.mutations.get_builder",
            return_value=lambda c, cid, p: [MagicMock(), MagicMock(), MagicMock()],
        ),
        patch(
            "src.google_ads.mutations.get_request_id",
            return_value="req-create-rs",
        ),
    ):
        # Step 1: Tool returns dry_run + confirmation token.
        dry_run_result = await create_conversion_value_rule_set(
            {
                "customer_id": "1234567890",
                "attachment_type": "CUSTOMER",
                "rules": [
                    {
                        "action": {"operation": "ADD", "value": 10.0},
                        "condition_type": "DEVICE",
                        "device_condition": {"device_types": ["MOBILE"]},
                    },
                    {
                        "action": {"operation": "ADD", "value": 30.0},
                        "condition_type": "GEO_LOCATION",
                        "geo_condition": {
                            "geo_target_constants": ["geoTargetConstants/20114"],
                            "geo_match_type": "ANY",
                        },
                    },
                ],
            }
        )

        assert dry_run_result["status"] == "dry_run"
        assert dry_run_result["operation"] == "create_conversion_value_rule_set"
        token = dry_run_result["confirmation_token"]
        assert token

        # Step 2: apply_change consumes token → dispatches run_mutation.
        apply_result = await apply_change({"confirmation_token": token})

    assert apply_result["status"] == "applied"
    assert apply_result["operation"] == "create_conversion_value_rule_set"
    # target_count = N rules + 1 set = 2 + 1 = 3
    assert apply_result["applied_count"] == 3
    assert apply_result["provider_request_id"] == "req-create-rs"

    # F13 (Sprint 3b.15) — chained mutation case: 3 resource_names in order.
    # Verifies ordering: rule1 path → rule2 path → set path, matching the
    # mock's 3 mutate_operation_responses with two distinct oneof field names.
    assert "resource_names" in apply_result
    assert isinstance(apply_result["resource_names"], list)
    assert len(apply_result["resource_names"]) == 3
    assert apply_result["resource_names"][0] == "customers/1234567890/conversionValueRules/11111"
    assert apply_result["resource_names"][1] == "customers/1234567890/conversionValueRules/22222"
    assert apply_result["resource_names"][2] == "customers/1234567890/conversionValueRuleSets/99999"

    # Step 3: Verify audit_log row has expected target_count + provider_request_id
    # + custom params_summary (counts only — no rule content per spec §3.6).
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT operation, target_count, params_summary, provider_request_id "
            "FROM audit_log WHERE operation = 'create_conversion_value_rule_set'"
        )
    assert len(rows) == 1
    assert rows[0]["target_count"] == 3
    assert rows[0]["provider_request_id"] == "req-create-rs"
    summary = rows[0]["params_summary"]
    summary_d = json.loads(summary) if isinstance(summary, str) else summary
    assert summary_d == {
        "rule_count": 2,
        "attachment_type": "CUSTOMER",
        "campaign_scoped": False,
        "operations": {"ADD": 2},
        "condition_types": {"DEVICE": 1, "GEO_LOCATION": 1},
    }
