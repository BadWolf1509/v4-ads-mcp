"""Integration test: import_offline_conversions full cycle (Sprint 3b.26).

Tests dry_run → apply_change → run_conversion_upload dispatched → applied
response with applied_count + failures + audit_log row.

First integration test exercising the apply_change branching introduced in
Sprint 3b.26 (operation_type-based dispatch to run_conversion_upload).
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


def _mock_upload_response(success_count: int, failure_count: int) -> MagicMock:
    """Mock UploadClickConversionsResponse with N successes + M failures."""
    response = MagicMock()
    results = []
    for i in range(success_count):
        r = MagicMock()
        r.conversion_action = "customers/1234567890/conversionActions/987654321"
        r.gclid = f"Cj0_OK_{i}"
        r.conversion_date_time = "2026-05-17 14:30:00-03:00"
        results.append(r)
    for _ in range(failure_count):
        r = MagicMock()
        r.conversion_action = ""  # empty = failed
        results.append(r)
    response.results = results

    pfe = MagicMock()
    pfe.code = 0 if failure_count == 0 else 1
    pfe.details = []
    response.partial_failure_error = pfe
    return response


async def test_import_offline_conversions_dry_run_emits_token_and_pending_row(
    db, session_ctx
) -> None:
    """Step 1 only: tool returns dry_run with token; pending_confirmations row created."""
    from src.mcp.tools.import_offline_conversions import import_offline_conversions

    with patch(
        "src.mcp.tools.import_offline_conversions.validate_conversion_action_for_upload",
        AsyncMock(return_value=None),
    ):
        args = {
            "customer_id": "1234567890",
            "conversion_action_id": "987654321",
            "conversions": [
                {
                    "gclid": "Cj0KCQjwTEST",
                    "conversion_date_time": "2026-05-17 14:30:00",
                    "conversion_value_brl": 150.0,
                }
            ],
        }
        result = await import_offline_conversions(args)

    assert result["status"] == "dry_run"
    assert result["operation"] == "import_offline_conversions"
    assert result["confirmation_token"]
    assert result["summary"]["conversion_count"] == 1
    assert result["summary"]["sum_value_brl"] == 150.0

    # Verify pending state in DB
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT operation_type, customer_id FROM pending_confirmations WHERE token = $1",
            result["confirmation_token"],
        )
    assert len(rows) == 1
    assert rows[0]["operation_type"] == "import_offline_conversions"
    assert rows[0]["customer_id"] == "1234567890"


async def test_import_offline_conversions_full_cycle_returns_applied_count_and_audit(
    db, session_ctx
) -> None:
    """Full cycle: dry_run → apply_change branches to run_conversion_upload →
    response with applied_count/failed_count/failures + audit_log row."""
    from src.mcp.tools.apply_change import apply_change
    from src.mcp.tools.import_offline_conversions import import_offline_conversions

    # Mock 3 successes + 2 failures
    fake_response = _mock_upload_response(success_count=3, failure_count=2)
    fake_service = MagicMock()
    fake_service.upload_click_conversions = MagicMock(return_value=fake_response)

    fake_client = MagicMock()
    fake_client.get_service = MagicMock(return_value=fake_service)
    fake_client.get_type = MagicMock(side_effect=lambda name: MagicMock())
    fake_client.enums.ConsentStatusEnum.GRANTED = "GRANTED"

    with (
        patch(
            "src.mcp.tools.import_offline_conversions.validate_conversion_action_for_upload",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.google_ads.conversions.build_client_for_manager",
            AsyncMock(return_value=fake_client),
        ),
        patch("src.google_ads.conversions.get_request_id", return_value="req-conv-int"),
        patch("src.google_ads.conversions.reset_request_id", return_value=None),
        patch("src.google_ads.conversions.before_call", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.record_actual", AsyncMock(return_value=None)),
    ):
        conversions = [
            {
                "gclid": f"Cj0_{i}",
                "conversion_date_time": "2026-05-17 14:30:00",
                "conversion_value_brl": 100.0,
            }
            for i in range(5)
        ]
        args = {
            "customer_id": "1234567890",
            "conversion_action_id": "987654321",
            "conversions": conversions,
        }
        dry_run_result = await import_offline_conversions(args)
        assert dry_run_result["status"] == "dry_run"
        token = dry_run_result["confirmation_token"]

        apply_result = await apply_change({"confirmation_token": token})

    assert apply_result["status"] == "applied"
    assert apply_result["operation"] == "import_offline_conversions"
    assert apply_result["applied_count"] == 3
    assert apply_result["failed_count"] == 2
    assert apply_result["provider_request_id"] == "req-conv-int"
    assert len(apply_result["failures"]) == 2
    # Failed rows are indices 3 and 4 (after 3 successes)
    assert apply_result["failures"][0]["row_index"] == 3
    assert apply_result["failures"][1]["row_index"] == 4
    # gclid echoed from input
    assert apply_result["failures"][0]["gclid"] == "Cj0_3"
    assert apply_result["failures"][1]["gclid"] == "Cj0_4"

    # audit_log: target_count=5 (input), params_summary from _build_summary
    # Note: audit_log schema has target_count (NOT applied_count column).
    # applied_count is only in the MCP response dict, not persisted separately.
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT operation, target_count, params_summary, provider_request_id "
            "FROM audit_log WHERE operation = 'import_offline_conversions'"
        )
    assert len(rows) == 1
    assert rows[0]["target_count"] == 5
    assert rows[0]["provider_request_id"] == "req-conv-int"
    summary = rows[0]["params_summary"]
    summary_d = json.loads(summary) if isinstance(summary, str) else summary
    assert summary_d["conversion_count"] == 5
    assert summary_d["sum_value_brl"] == 500.0
    assert summary_d["conversion_action_id"] == "987654321"
