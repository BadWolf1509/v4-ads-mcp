"""Integration tests for remove_audience (real Postgres, mocked SDK surface).

Tests the full cycle:
  remove_audience(args) → dry_run + token → apply_change(token) → run_mutation
  → builder dispatch → audit_log row with custom params_summary.

Uses proto-plus surface fixture pattern (Sprint 3b.1/3b.3 lesson) — explicit
_pb.WhichOneof stubbing rather than MagicMock-everywhere.
"""

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

    Mirrors Sprint 3b.3/3b.4 test pattern. Each entry: None = success,
    string = error message. Uses ad_group_criterion_result oneof name
    (for ad_group target_type test).
    """
    client = MagicMock()
    fake_responses = []
    for err in per_op_errors:
        r = MagicMock()
        if err is None:
            r._pb.WhichOneof = MagicMock(return_value="ad_group_criterion_result")
        else:
            r._pb.WhichOneof = MagicMock(return_value=None)
        fake_responses.append(r)

    response = MagicMock()
    response.mutate_operation_responses = fake_responses

    failed_indices = [i for i, e in enumerate(per_op_errors) if e is not None]
    if failed_indices:
        response.partial_failure_error.code = 1
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
async def test_remove_audience_full_cycle_audits(db, session_ctx):
    """3 criteria (2 removed + 1 already_removed via NOT_FOUND) → CONFIRM dry_run →
    apply_change consumes token → run_mutation with partial_failure → audit_log row
    with custom params_summary.
    """
    from src.mcp.tools.apply_change import apply_change
    from src.mcp.tools.remove_audience import remove_audience

    # Step 1: Tool returns dry_run + token
    dry_run_result = await remove_audience(
        {
            "customer_id": "1234567890",
            "target_type": "ad_group",
            "target_id": "111",
            "criterion_ids": ["100", "200", "300"],
        }
    )
    assert dry_run_result["status"] == "dry_run"
    token = dry_run_result["confirmation_token"]
    assert token

    # Step 2: apply_change consumes token → dispatches via run_mutation
    fake_client = _client_with_responses(
        [
            None,
            "RESOURCE_NOT_FOUND: criterion does not exist",
            None,
        ]
    )

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
            return_value="req-remove-aud",
        ),
    ):
        apply_result = await apply_change({"confirmation_token": token})

    # apply_change returns the run_mutation result directly
    assert apply_result["status"] == "applied"
    assert apply_result["applied_count"] == 2  # 2 removed + 1 already_removed

    # Step 3: Verify audit_log row has expected target_count + provider_request_id +
    # custom params_summary
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT operation, target_count, params_summary, provider_request_id "
            "FROM audit_log WHERE operation = 'remove_audience' AND dry_run IS NOT TRUE"
        )
    assert len(rows) == 1, "a consulta filtra dry_run; so a linha APLICADA conta"

    # F148: o preview tambem deixa rastro, com a contagem PLANEJADA e
    # `dry_run=true`. Antes do fix esta linha nao existia e o fluxo inteiro
    # aparecia na trilha como uma unica escrita, a aplicada.
    async with pool.acquire() as conn:
        previews = await conn.fetch(
            "SELECT action_type, target_count, dry_run FROM audit_log "
            "WHERE operation = 'remove_audience' AND dry_run IS TRUE"
        )
    assert len(previews) == 1, "o dry-run tem que deixar exatamente uma linha"
    assert previews[0]["action_type"] == "mutate"
    assert previews[0]["target_count"] is not None, (
        "target_count NULL significa que a tool nao declarou __target_count__"
    )
    assert rows[0]["target_count"] == 3
    assert rows[0]["provider_request_id"] == "req-remove-aud"
    summary = rows[0]["params_summary"]
    summary_d = json.loads(summary) if isinstance(summary, str) else summary
    assert summary_d == {
        "target_type": "ad_group",
        "target_id": "111",
        "criterion_count": 3,
    }
