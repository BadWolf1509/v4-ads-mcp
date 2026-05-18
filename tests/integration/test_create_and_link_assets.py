"""Integration test: create_and_link_assets full cycle (Sprint 3b.25).

Tests dry_run → apply_change → builder runs chained mutation → applied
response with 2N resource_names. F13 cross-cutting tested em chained
mutation case (paralleled to Sprint 3b.19B 3-resource test, but 2N here).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.db.repositories import managers, mcp_sessions
from src.mcp.context import McpRequestContext, clear_current, set_current

pytestmark = pytest.mark.integration


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


def _client_with_chained_response_for_n_assets(n: int) -> MagicMock:
    """Mock SDK client returning 2N mutate_operation_responses (N asset + N link)."""
    client = MagicMock()

    op_responses = []
    for i in range(n):
        # Asset result
        asset_resp = MagicMock()
        asset_proto = MagicMock()
        asset_proto.resource_name = f"customers/1234567890/assets/{1000 + i}"
        asset_resp._pb.WhichOneof = MagicMock(return_value="asset_result")
        asset_resp._pb.asset_result = asset_proto
        op_responses.append(asset_resp)

        # Link result (campaign_asset_result for CAMPAIGN-level test)
        link_resp = MagicMock()
        link_proto = MagicMock()
        link_proto.resource_name = f"customers/1234567890/campaignAssets/99999~{1000 + i}~SITELINK"
        link_resp._pb.WhichOneof = MagicMock(return_value="campaign_asset_result")
        link_resp._pb.campaign_asset_result = link_proto
        op_responses.append(link_resp)

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


async def test_create_and_link_assets_dry_run_emits_token_and_audit_pending(
    db, session_ctx
) -> None:
    """Step 1 only: tool returns dry_run with token; no apply yet."""
    from src.mcp.tools.create_and_link_assets import create_and_link_assets

    args = {
        "customer_id": "1234567890",
        "assets": [
            {
                "type": "SITELINK",
                "attachment_level": "CAMPAIGN",
                "attachment_id": "customers/1234567890/campaigns/99999",
                "link_text": "Sobre",
                "final_urls": ["https://example.com/sobre"],
            },
        ],
    }

    result = await create_and_link_assets(args)

    assert result["status"] == "dry_run"
    assert result["operation"] == "create_and_link_assets"
    assert result["confirmation_token"]
    assert result["summary"]["asset_count"] == 1
    assert result["summary"]["total_ops_chained"] == 2

    # Verify pending state in DB (no audit_log row yet — that's apply step)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT operation_type, customer_id FROM pending_mutations "
            "WHERE confirmation_token = $1",
            result["confirmation_token"],
        )
    assert len(rows) == 1
    assert rows[0]["operation_type"] == "create_and_link_assets"
    assert rows[0]["customer_id"] == "1234567890"


async def test_create_and_link_assets_full_cycle_returns_interleaved_resource_names_and_audit_applied(
    db, session_ctx
) -> None:
    """Full cycle: dry_run → apply_change → 2n resource_names + audit_log applied."""
    from src.mcp.tools.apply_change import apply_change
    from src.mcp.tools.create_and_link_assets import create_and_link_assets

    asset_count = 3
    two_n = 2 * asset_count
    fake_client = _client_with_chained_response_for_n_assets(asset_count)

    with (
        patch(
            "src.google_ads.mutations.build_client_for_manager",
            AsyncMock(return_value=fake_client),
        ),
        patch(
            "src.google_ads.mutations.get_builder",
            return_value=lambda c, cid, p: [MagicMock() for _ in range(two_n)],
        ),
        patch(
            "src.google_ads.mutations.get_request_id",
            return_value="req-create-assets",
        ),
    ):
        # Step 1: dry_run
        assets = [
            {
                "type": "SITELINK",
                "attachment_level": "CAMPAIGN",
                "attachment_id": "customers/1234567890/campaigns/99999",
                "link_text": f"Page {i}",
                "final_urls": [f"https://example.com/{i}"],
            }
            for i in range(asset_count)
        ]
        dry_run_result = await create_and_link_assets(
            {
                "customer_id": "1234567890",
                "assets": assets,
            }
        )

        assert dry_run_result["status"] == "dry_run"
        token = dry_run_result["confirmation_token"]
        assert token

        # Step 2: apply_change
        apply_result = await apply_change({"confirmation_token": token})

    assert apply_result["status"] == "applied"
    assert apply_result["operation"] == "create_and_link_assets"
    assert apply_result["applied_count"] == two_n  # 2N ops
    assert apply_result["google_request_id"] == "req-create-assets"

    # F13 cross-cutting: 2N resource_names, ordering [asset0, link0, asset1, link1, ...]
    assert "resource_names" in apply_result
    assert len(apply_result["resource_names"]) == two_n
    for i in range(asset_count):
        assert apply_result["resource_names"][2 * i] == f"customers/1234567890/assets/{1000 + i}"
        assert (
            apply_result["resource_names"][2 * i + 1]
            == f"customers/1234567890/campaignAssets/99999~{1000 + i}~SITELINK"
        )

    # audit_log: target_count = 2N, custom params_summary
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT operation, target_count, params_summary, google_request_id "
            "FROM audit_log WHERE operation = 'create_and_link_assets'"
        )
    assert len(rows) == 1
    assert rows[0]["target_count"] == two_n
    assert rows[0]["google_request_id"] == "req-create-assets"
    summary = rows[0]["params_summary"]
    summary_d = json.loads(summary) if isinstance(summary, str) else summary
    assert summary_d["asset_count"] == asset_count
    assert summary_d["by_type"] == {"SITELINK": asset_count}
    assert summary_d["by_level"] == {"CAMPAIGN": asset_count}
    assert summary_d["total_ops_chained"] == two_n
