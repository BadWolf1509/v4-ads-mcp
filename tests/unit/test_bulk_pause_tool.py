"""Unit tests for bulk_pause_by_query MCP tool's branching logic.

Mocks run_report so we can drive the row-count branches without SDK.
"""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from jsonschema import ValidationError, validate


@pytest.fixture(autouse=True)
def _ctx():
    from src.mcp.context import McpRequestContext, clear_current, set_current

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def test_schema_accepts_minimal():
    from src.mcp.tools.bulk_pause_by_query import _SCHEMA

    validate(
        {
            "customer_id": "1234567890",
            "target_type": "keyword",
            "filter": "metrics.cost_micros > 100000000",
        },
        _SCHEMA,
    )


def test_schema_rejects_unknown_target_type():
    from src.mcp.tools.bulk_pause_by_query import _SCHEMA

    with pytest.raises(ValidationError):
        validate(
            {"customer_id": "1234567890", "target_type": "galaxy", "filter": "x = 1"},
            _SCHEMA,
        )


@pytest.mark.asyncio
async def test_zero_matches_returns_no_op(monkeypatch):
    """When run_report returns 0 rows, tool returns status:'no_op' without creating a token."""
    from src.mcp.tools import bulk_pause_by_query as mod

    create_pending_mock = AsyncMock()

    async def fake_run_report(**_kwargs):
        return []

    monkeypatch.setattr(mod, "run_report", fake_run_report)
    monkeypatch.setattr(mod, "create_pending", create_pending_mock)

    result = await mod.bulk_pause_by_query(
        {
            "customer_id": "1234567890",
            "target_type": "keyword",
            "filter": "ad_group_criterion.status = 'ENABLED'",
        }
    )

    assert result["status"] == "no_op"
    assert result["matched_count"] == 0
    create_pending_mock.assert_not_called()


@pytest.mark.asyncio
async def test_overflow_returns_error(monkeypatch):
    """When run_report returns 101 rows, tool returns status:'error' and matched_count='100+'."""
    from src.mcp.tools import bulk_pause_by_query as mod

    create_pending_mock = AsyncMock()

    async def fake_run_report(**_kwargs):
        # 101 fake rows simulating LIMIT 101 hit
        return [{"id": str(i)} for i in range(101)]

    monkeypatch.setattr(mod, "run_report", fake_run_report)
    monkeypatch.setattr(mod, "create_pending", create_pending_mock)

    result = await mod.bulk_pause_by_query(
        {
            "customer_id": "1234567890",
            "target_type": "keyword",
            "filter": "metrics.cost_micros > 0",
        }
    )

    assert result["status"] == "error"
    assert result["matched_count"] == "100+"
    assert "100" in result["error_message"]
    create_pending_mock.assert_not_called()


@pytest.mark.asyncio
async def test_valid_count_creates_token_with_capture(monkeypatch):
    """When 1 <= count <= 100, tool creates token + captures entities in payload."""
    from src.mcp.tools import bulk_pause_by_query as mod

    async def fake_run_report(**_kwargs):
        return [
            {
                "ad_group_id": "111",
                "criterion_id": "200",
                "keyword_text": "test 1",
                "campaign_name": "Camp A",
                "ad_group_name": "AG 1",
                "cost_brl": 12.5,
            },
            {
                "ad_group_id": "112",
                "criterion_id": "201",
                "keyword_text": "test 2",
                "campaign_name": "Camp A",
                "ad_group_name": "AG 1",
                "cost_brl": 25.0,
            },
        ]

    captured_payload: dict = {}

    async def fake_create_pending(conn, **kwargs):
        captured_payload.update(kwargs.get("payload", {}))
        return "TOK01234"

    monkeypatch.setattr(mod, "run_report", fake_run_report)
    monkeypatch.setattr(mod, "create_pending", fake_create_pending)
    # Patch the pool acquisition path
    with patch("src.mcp.tools.bulk_pause_by_query.connection") as conn_module:
        conn_module.get_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(
            return_value=AsyncMock()
        )
        conn_module.get_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(
            return_value=None
        )

        result = await mod.bulk_pause_by_query(
            {
                "customer_id": "1234567890",
                "target_type": "keyword",
                "filter": "metrics.cost_micros > 0 AND metrics.conversions = 0",
            }
        )

    assert result["status"] == "dry_run"
    assert result["confirmation_token"] == "TOK01234"
    assert result["preview"]["matched_count"] == 2
    assert captured_payload["target_type"] == "keyword"
    assert len(captured_payload["entities"]) == 2
    assert captured_payload["entities"][0]["ad_group_id"] == "111"
    assert captured_payload["entities"][0]["criterion_id"] == "200"


@pytest.mark.asyncio
async def test_invalid_filter_returns_error(monkeypatch):
    """Tool catches FilterValidationError and converts to status:'error' dict."""
    from src.mcp.tools import bulk_pause_by_query as mod

    create_pending_mock = AsyncMock()
    run_report_mock = AsyncMock()
    monkeypatch.setattr(mod, "run_report", run_report_mock)
    monkeypatch.setattr(mod, "create_pending", create_pending_mock)

    result = await mod.bulk_pause_by_query(
        {
            "customer_id": "1234567890",
            "target_type": "keyword",
            "filter": "metrics.cost_micros > 0; DROP TABLE users",
        }
    )

    assert result["status"] == "error"
    # Verify the PT-BR message reaches the user
    assert "ponto-e-virgula" in result["error_message"].lower() or ";" in result["error_message"]
    # Critical: no API call, no token creation
    run_report_mock.assert_not_called()
    create_pending_mock.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_date_range_returns_error(monkeypatch):
    """Tool catches InvalidDateRangeError and converts to status:'error'."""
    from src.mcp.tools import bulk_pause_by_query as mod

    run_report_mock = AsyncMock()
    create_pending_mock = AsyncMock()
    monkeypatch.setattr(mod, "run_report", run_report_mock)
    monkeypatch.setattr(mod, "create_pending", create_pending_mock)

    result = await mod.bulk_pause_by_query(
        {
            "customer_id": "1234567890",
            "target_type": "keyword",
            "filter": "ad_group_criterion.status = 'ENABLED'",
            "date_range": "LAST_FORTNIGHT",  # invalid preset
        }
    )

    assert result["status"] == "error"
    assert "date_range" in result["error_message"].lower()
    run_report_mock.assert_not_called()
    create_pending_mock.assert_not_called()
