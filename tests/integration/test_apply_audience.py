"""Integration tests for apply_audience (real Postgres, mocked SDK surface)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.db.repositories import managers, mcp_sessions
from src.mcp.context import McpRequestContext, clear_current, set_current


@pytest.fixture
async def pg() -> PostgresContainer:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture
async def db(pg):
    dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        await migrate.run_all()
        yield connection.get_pool()
    finally:
        await connection.close_pool()


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
    ctx = McpRequestContext(manager_id=mid, session_id=sess.id)
    set_current(ctx)
    yield ctx
    clear_current()


def _client_with_responses(per_op_errors):
    """Mock SDK client whose mutate() returns response with per-op statuses.

    Mirrors Sprint 3b.3 test pattern. Each entry: None = success, string = error.
    Uses ad_group_criterion_result oneof name (for ad_group target_type test).
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
async def test_apply_audience_full_cycle_audits(db, session_ctx):
    """3 attachments (2 success + 1 CRITERION_EXISTS) → run_mutation with
    partial_failure → audit_log with custom params_summary.
    """
    from src.mcp.tools.apply_audience import apply_audience

    fake_client = _client_with_responses(
        [
            None,
            "CRITERION_EXISTS: criterion already exists",
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
            return_value="req-apply-aud",
        ),
    ):
        result = await apply_audience(
            {
                "customer_id": "1234567890",
                "target_type": "ad_group",
                "mode": "observation",
                "attachments": [
                    {
                        "target_id": "111",
                        "audience_type": "user_list",
                        "audience_resource_name": "customers/1234567890/userLists/AAA",
                        "bid_modifier": 1.5,
                    },
                    {
                        "target_id": "111",
                        "audience_type": "user_interest",
                        "audience_resource_name": "customers/1234567890/userInterests/BBB",
                    },
                    {
                        "target_id": "222",
                        "audience_type": "user_interest",
                        "audience_resource_name": "customers/1234567890/userInterests/CCC",
                    },
                ],
            }
        )

    assert result["status"] == "applied"
    assert result["applied_count"] == 2  # 2 succeeded, 1 already_attached
    assert result["attachments_result"][0]["status"] == "attached"
    assert result["attachments_result"][1]["status"] == "already_attached"
    assert result["attachments_result"][2]["status"] == "attached"

    # Verify audit_log row has the custom params_summary
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT operation, target_count, params_summary, google_request_id "
            "FROM audit_log WHERE operation = 'apply_audience'"
        )
    assert len(rows) == 1
    assert rows[0]["target_count"] == 3
    assert rows[0]["google_request_id"] == "req-apply-aud"
    summary = rows[0]["params_summary"]
    summary_d = json.loads(summary) if isinstance(summary, str) else summary
    assert summary_d == {
        "target_type": "ad_group",
        "mode": "observation",
        "audience_types_distribution": {"user_list": 1, "user_interest": 2},
        "with_bid_modifier_count": 1,
        "unique_targets_count": 2,
    }
    # Critical privacy gate: raw resource_name fragments NOT in audit
    for fragment in ("AAA", "BBB", "CCC", "userLists/A", "userInterests/B"):
        assert fragment not in json.dumps(summary_d)
