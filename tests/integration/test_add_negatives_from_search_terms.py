"""Integration tests for add_negatives_from_search_terms (real Postgres, mocked SDK)."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.db import connection
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


def _client_with_responses(per_op_errors):
    """Build a fake SDK client where mutate() returns a response with per-op statuses.

    Simulates the real API shape:
    - Top-level partial_failure_error.code is 0 if all OK, else non-zero
    - Top-level partial_failure_error.details contains a GoogleAdsFailure-like
      proto with per-op locations (we mock the unpack via index_to_error)
    - Each MutateOperationResponse has _pb.WhichOneof('response') returning
      a field name (success) or None (failure)
    """
    client = MagicMock()

    # Build per-op mock responses with realistic WhichOneof behavior
    fake_responses = []
    for _idx, err in enumerate(per_op_errors):
        r = MagicMock()
        if err is None:
            r._pb.WhichOneof = MagicMock(return_value="campaign_criterion_result")
        else:
            r._pb.WhichOneof = MagicMock(return_value=None)
        fake_responses.append(r)

    # Build top-level response
    response = MagicMock(mutate_operation_responses=fake_responses)

    # If any op failed, top-level partial_failure_error has non-zero code +
    # a single details entry we'll cause the unpack path to populate
    # error_by_index with the per_op_errors values.
    failed_indices = [i for i, e in enumerate(per_op_errors) if e is not None]
    if failed_indices:
        # Simulate a GoogleAdsFailure detail. The implementation duck-type-checks
        # for hasattr(raw, "type_url") and hasattr(raw, "Unpack") — MagicMock
        # satisfies both automatically. We just set type_url and stub Unpack.
        class _FakeError:
            def __init__(self, idx, msg):
                self.message = msg
                self.location = MagicMock()
                self.location.field_path_elements = [MagicMock(index=idx)]

        fake_errors = [_FakeError(i, per_op_errors[i]) for i in failed_indices]

        def fake_unpack(target_pb):
            target_pb.errors = fake_errors

        raw_any = MagicMock()
        raw_any.type_url = "type.googleapis.com/google.ads.googleads.v20.errors.GoogleAdsFailure"
        raw_any.Unpack = fake_unpack

        fake_detail = MagicMock()
        fake_detail._pb = raw_any

        response.partial_failure_error.code = 1
        response.partial_failure_error.details = [fake_detail]

        failure_type_stub = MagicMock()
        failure_type_stub._meta.pb = lambda: MagicMock(errors=[])
    else:
        response.partial_failure_error.code = 0
        response.partial_failure_error.details = []
        failure_type_stub = MagicMock()
        failure_type_stub._meta.pb = lambda: MagicMock(errors=[])

    fake_service = MagicMock()
    fake_service.mutate = MagicMock(return_value=response)
    client.get_service = MagicMock(return_value=fake_service)

    def get_type(name):
        if name == "GoogleAdsFailure":
            return failure_type_stub
        return MagicMock(mutate_operations=[], partial_failure_mode=MagicMock())

    client.get_type = MagicMock(side_effect=get_type)
    client.enums.PartialFailureModeEnum.PARTIAL_FAILURE = "PARTIAL_FAILURE"
    return client


@pytest.mark.integration
async def test_add_negatives_from_search_terms_full_cycle_audits(db, session_ctx):
    """End-to-end: call tool -> mocked SDK accepts -> audit_log row created with custom summary."""
    from src.mcp.tools.add_negatives_from_search_terms import add_negatives_from_search_terms

    fake_client = _client_with_responses([None, None, "CRITERION_EXISTS"])

    with (
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
            return_value="req-int",
        ),
    ):
        result = await add_negatives_from_search_terms(
            {
                "customer_id": "1234567890",
                "negatives": [
                    {
                        "search_term": "a",
                        "match_type": "EXACT",
                        "scope": "campaign",
                        "scope_id": "111",
                    },
                    {
                        "search_term": "b",
                        "match_type": "EXACT",
                        "scope": "ad_group",
                        "scope_id": "222",
                    },
                    {
                        "search_term": "c",
                        "match_type": "PHRASE",
                        "scope": "campaign",
                        "scope_id": "111",
                    },
                ],
            }
        )

    assert result["status"] == "applied"
    assert result["applied_count"] == 2  # 2 added, 1 already_exists
    assert result["added"][0]["status"] == "added"
    assert result["added"][1]["status"] == "added"
    assert result["added"][2]["status"] == "already_exists"

    # Audit row created with custom params_summary
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT operation, target_count, params_summary, provider_request_id "
            "FROM audit_log WHERE operation = 'add_negatives_from_search_terms'"
        )
    assert len(rows) == 1
    assert rows[0]["target_count"] == 3
    assert rows[0]["provider_request_id"] == "req-int"
    summary = rows[0]["params_summary"]
    import json

    summary_d = json.loads(summary) if isinstance(summary, str) else summary
    assert summary_d == {
        "scopes_distribution": {"campaign": 2, "ad_group": 1},
        "match_types_distribution": {"EXACT": 2, "PHRASE": 1},
        "scope_ids_count": 2,
    }
