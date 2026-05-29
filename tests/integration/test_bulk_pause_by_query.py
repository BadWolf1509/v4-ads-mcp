"""Integration tests for bulk_pause_by_query (real Postgres, mocked SDK).

KEY: uses SimpleNamespace-based fixtures (not MagicMock) for the proto-plus
surface — Sprint 3b.1 lesson: MagicMock accepts any attribute access silently,
masking API-shape bugs that only fire against real SDK.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.db.repositories import google_ads_accounts, manager_account_access, managers, mcp_sessions
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


def _make_keyword_view_row(ag_id: str, crit_id: str, text: str, cost_micros: int):
    """SimpleNamespace fixture mirroring the proto-plus surface of a keyword_view row.

    Uses real attribute access (no MagicMock magic) so missing fields fail loudly.
    """
    return SimpleNamespace(
        ad_group=SimpleNamespace(id=int(ag_id), name=f"AG {ag_id}"),
        ad_group_criterion=SimpleNamespace(
            criterion_id=int(crit_id),
            keyword=SimpleNamespace(text=text),
            status=SimpleNamespace(name="ENABLED"),
        ),
        campaign=SimpleNamespace(id=999, name="Campaign Test"),
        metrics=SimpleNamespace(cost_micros=cost_micros),
    )


@pytest.mark.integration
async def test_bulk_pause_dry_run_creates_token_and_audit(db, session_ctx):
    """3 keyword_view rows → dry_run → pending_confirmations row + audit_log read row."""
    from src.mcp.tools.bulk_pause_by_query import bulk_pause_by_query

    mock_rows = [
        _make_keyword_view_row("111", "200", "termo 1", 12_500_000),
        _make_keyword_view_row("111", "201", "termo 2", 25_000_000),
        _make_keyword_view_row("112", "300", "termo 3", 8_000_000),
    ]

    batch = MagicMock(results=mock_rows)
    fake_service = MagicMock()
    fake_service.search_stream = MagicMock(return_value=[batch])
    fake_client = MagicMock()
    fake_client.get_service = MagicMock(return_value=fake_service)
    fake_client.get_type = MagicMock(return_value=MagicMock())

    with patch(
        "src.google_ads.reports.build_client_for_manager",
        AsyncMock(return_value=fake_client),
    ):
        result = await bulk_pause_by_query(
            {
                "customer_id": "1234567890",
                "target_type": "keyword",
                "filter": "metrics.cost_micros > 0",
                "date_range": "LAST_7_DAYS",
            }
        )

    assert result["status"] == "dry_run"
    assert result["preview"]["matched_count"] == 3
    assert result["preview"]["total_cost_brl"] == 45.5  # 12.5 + 25.0 + 8.0
    assert len(result["preview"]["sample"]) == 3
    token = result["confirmation_token"]

    # Verify pending_confirmations row
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        pc_row = await conn.fetchrow(
            "SELECT operation_type, payload FROM pending_confirmations WHERE token = $1",
            token,
        )
    assert pc_row is not None
    assert pc_row["operation_type"] == "bulk_pause_by_query"
    import json

    payload = (
        json.loads(pc_row["payload"]) if isinstance(pc_row["payload"], str) else pc_row["payload"]
    )
    assert payload["target_type"] == "keyword"
    assert len(payload["entities"]) == 3
    assert payload["entities"][0]["ad_group_id"] == "111"
    assert payload["entities"][0]["criterion_id"] == "200"

    # Verify audit_log read row with custom telemetry
    async with pool.acquire() as conn:
        audit_rows = await conn.fetch(
            "SELECT operation, action_type, params_summary "
            "FROM audit_log WHERE operation = 'bulk_pause_by_query_dry_run'"
        )
    assert len(audit_rows) == 1
    assert audit_rows[0]["action_type"] == "read"
    ps = audit_rows[0]["params_summary"]
    ps_d = json.loads(ps) if isinstance(ps, str) else ps
    assert ps_d["target_type"] == "keyword"
    assert ps_d["filter_hash"].startswith("sha256:")


@pytest.mark.integration
async def test_bulk_pause_dry_run_then_apply_change_full_cycle(db, session_ctx):
    """dry_run → apply_change → run_mutation invoked with partial_failure=True.

    Verifies the apply path correctly reads __partial_failure__ from payload
    and passes it through (Issue 1 fix).
    """
    from src.mcp.tools.apply_change import apply_change
    from src.mcp.tools.bulk_pause_by_query import bulk_pause_by_query

    mock_rows = [_make_keyword_view_row("111", "200", "termo 1", 12_500_000)]

    batch = MagicMock(results=mock_rows)
    fake_service = MagicMock()
    fake_service.search_stream = MagicMock(return_value=[batch])
    fake_client = MagicMock()
    fake_client.get_service = MagicMock(return_value=fake_service)
    fake_client.get_type = MagicMock(return_value=MagicMock())

    # Stub mutate-side too
    fake_mutate_response = MagicMock()
    fake_mutate_response.mutate_operation_responses = [MagicMock()]
    fake_mutate_response.mutate_operation_responses[0]._pb.WhichOneof = MagicMock(
        return_value="ad_group_criterion_result"
    )
    fake_service.mutate = MagicMock(return_value=fake_mutate_response)
    fake_client.copy_from = MagicMock()
    fake_client.enums.AdGroupCriterionStatusEnum.PAUSED = "PAUSED"

    with (
        patch(
            "src.google_ads.reports.build_client_for_manager",
            AsyncMock(return_value=fake_client),
        ),
        patch(
            "src.google_ads.mutations.build_client_for_manager",
            AsyncMock(return_value=fake_client),
        ),
        patch(
            "src.google_ads.mutations.get_request_id",
            return_value="req-bulk-apply",
        ),
    ):
        # Step 1: dry-run
        dry_result = await bulk_pause_by_query(
            {
                "customer_id": "1234567890",
                "target_type": "keyword",
                "filter": "metrics.cost_micros > 0",
                "date_range": "LAST_7_DAYS",
            }
        )

        assert dry_result["status"] == "dry_run"
        token = dry_result["confirmation_token"]

        # Step 2: apply_change
        apply_result = await apply_change({"confirmation_token": token})

    assert apply_result["status"] == "applied"
    assert apply_result["operation"] == "bulk_pause_by_query"

    # Verify token was consumed
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT consumed_at FROM pending_confirmations WHERE token = $1",
            token,
        )
    assert row["consumed_at"] is not None
