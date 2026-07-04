"""Integration tests for add_keywords (real Postgres, mocked SDK surface)."""

import json
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
    """Mock SDK client whose mutate() returns response with per-op statuses.

    Mirrors Sprint 3b.1 test pattern. Each entry: None = success,
    string = error message.
    """
    client = MagicMock()
    fake_responses = []
    for err in per_op_errors:
        r = MagicMock()
        # _pb.WhichOneof reports the set oneof field name on success, None on failure
        if err is None:
            r._pb.WhichOneof = MagicMock(return_value="ad_group_criterion_result")
        else:
            r._pb.WhichOneof = MagicMock(return_value=None)
        fake_responses.append(r)

    response = MagicMock()
    response.mutate_operation_responses = fake_responses

    # Top-level partial_failure_error: set non-zero code if any errors present
    failed_indices = [i for i, e in enumerate(per_op_errors) if e is not None]
    if failed_indices:
        response.partial_failure_error.code = 1
        # Stub details with a GoogleAdsFailure-like object
        fake_detail = MagicMock()
        fake_detail._pb = fake_detail
        fake_detail.type_url = (
            "type.googleapis.com/google.ads.googleads.v20.errors.GoogleAdsFailure"
        )

        class _FakeError:
            def __init__(self, idx, msg):
                self.message = msg
                self.location = MagicMock()
                self.location.field_path_elements = [MagicMock(index=idx)]

        fake_failure_pb = MagicMock()
        fake_failure_pb.errors = [_FakeError(i, per_op_errors[i]) for i in failed_indices]

        def fake_unpack(target_pb):
            target_pb.errors = fake_failure_pb.errors

        fake_detail.Unpack = fake_unpack
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
        return MagicMock(
            mutate_operations=[],
            partial_failure_mode=MagicMock(),
        )

    client.get_type = MagicMock(side_effect=get_type)
    client.enums.PartialFailureModeEnum.PARTIAL_FAILURE = "PARTIAL_FAILURE"
    return client


@pytest.mark.integration
async def test_add_keywords_full_cycle_audits(db, session_ctx):
    """3 KWs (2 added, 1 CRITERION_EXISTS) → run_mutation called with partial_failure → audit row with custom params_summary."""
    from src.mcp.tools.add_keywords import add_keywords

    fake_client = _client_with_responses([None, "CRITERION_EXISTS: keyword already exists", None])

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
    }
    # Critical: raw keyword texts NOT in audit
    assert "alpha" not in json.dumps(summary_d)
    assert "beta" not in json.dumps(summary_d)
