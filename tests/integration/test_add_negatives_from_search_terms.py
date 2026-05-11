"""Integration tests for add_negatives_from_search_terms (real Postgres, mocked SDK)."""

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
    """Build a fake SDK client where mutate() returns a response with per-op statuses."""
    client = MagicMock()
    fake_responses = []
    for err in per_op_errors:
        r = MagicMock()
        if err:
            r.HasField = lambda f, e=err: f == "partial_failure_error"
            r.partial_failure_error.message = err
        else:
            r.HasField = lambda f: False
        fake_responses.append(r)
    response = MagicMock(mutate_operation_responses=fake_responses)
    fake_service = MagicMock()
    fake_service.mutate = MagicMock(return_value=response)
    client.get_service = MagicMock(return_value=fake_service)
    client.get_type = MagicMock(
        return_value=MagicMock(mutate_operations=[], partial_failure_mode=MagicMock())
    )
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
            "SELECT operation, target_count, params_summary, google_request_id "
            "FROM audit_log WHERE operation = 'add_negatives_from_search_terms'"
        )
    assert len(rows) == 1
    assert rows[0]["target_count"] == 3
    assert rows[0]["google_request_id"] == "req-int"
    summary = rows[0]["params_summary"]
    import json

    summary_d = json.loads(summary) if isinstance(summary, str) else summary
    assert summary_d == {
        "scopes_distribution": {"campaign": 2, "ad_group": 1},
        "match_types_distribution": {"EXACT": 2, "PHRASE": 1},
        "scope_ids_count": 2,
    }
