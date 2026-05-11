"""Unit tests for the get_change_history MCP tool's pure logic.

The output-formatting + summary aggregation pieces are testable without
SDK or DB. Full I/O integration is covered in tests/integration/.
"""

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
    from src.mcp.tools.get_change_history import _SCHEMA

    validate({"customer_id": "1234567890"}, _SCHEMA)


def test_schema_accepts_full():
    from src.mcp.tools.get_change_history import _SCHEMA

    validate(
        {
            "customer_id": "1234567890",
            "date_range": "LAST_7_DAYS",
            "resource_types": ["CAMPAIGN", "AD_GROUP"],
            "operation_types": ["UPDATE"],
            "user_emails": ["fulano@v4company.com"],
            "client_types": ["GOOGLE_ADS_UI"],
            "limit": 500,
        },
        _SCHEMA,
    )


def test_schema_rejects_unknown_resource_type():
    from src.mcp.tools.get_change_history import _SCHEMA

    with pytest.raises(ValidationError):
        validate(
            {"customer_id": "1234567890", "resource_types": ["GALAXY"]},
            _SCHEMA,
        )


def test_schema_rejects_unknown_client_type():
    from src.mcp.tools.get_change_history import _SCHEMA

    with pytest.raises(ValidationError):
        validate(
            {"customer_id": "1234567890", "client_types": ["MARS_ROVER"]},
            _SCHEMA,
        )


def test_summary_aggregation_with_mixed_events():
    """Given 8 mock rows (3 auto-apply, 5 manual), summary must aggregate correctly."""
    from src.mcp.tools.get_change_history import _build_summary

    rows = [
        {
            "user_email": "fulano@v4company.com",
            "client_type": "GOOGLE_ADS_UI",
            "resource_type": "CAMPAIGN",
            "operation": "UPDATE",
        },
        {
            "user_email": "fulano@v4company.com",
            "client_type": "GOOGLE_ADS_UI",
            "resource_type": "AD_GROUP_CRITERION",
            "operation": "UPDATE",
        },
        {
            "user_email": "fulano@v4company.com",
            "client_type": "GOOGLE_ADS_UI",
            "resource_type": "AD_GROUP_CRITERION",
            "operation": "CREATE",
        },
        {
            "user_email": "ana@v4company.com",
            "client_type": "GOOGLE_ADS_UI",
            "resource_type": "BIDDING_STRATEGY",
            "operation": "UPDATE",
        },
        {
            "user_email": "ana@v4company.com",
            "client_type": "GOOGLE_ADS_UI",
            "resource_type": "CAMPAIGN",
            "operation": "REMOVE",
        },
        {
            "user_email": "google-ads-svc@google.com",
            "client_type": "GOOGLE_ADS_RECOMMENDATIONS_AUTO_APPLY",
            "resource_type": "CAMPAIGN",
            "operation": "UPDATE",
        },
        {
            "user_email": "google-ads-svc@google.com",
            "client_type": "GOOGLE_ADS_RECOMMENDATIONS_AUTO_APPLY",
            "resource_type": "AD_GROUP",
            "operation": "UPDATE",
        },
        {
            "user_email": "google-ads-svc@google.com",
            "client_type": "GOOGLE_ADS_RECOMMENDATIONS_AUTO_APPLY",
            "resource_type": "AD_GROUP",
            "operation": "CREATE",
        },
    ]
    summary = _build_summary(rows)

    assert summary["total_changes"] == 8
    assert summary["by_user"] == {
        "fulano@v4company.com": 3,
        "ana@v4company.com": 2,
        "auto-apply": 3,  # auto-apply rows collapsed into synthetic bucket
    }
    assert summary["by_resource_type"] == {
        "CAMPAIGN": 3,
        "AD_GROUP_CRITERION": 2,
        "BIDDING_STRATEGY": 1,
        "AD_GROUP": 2,
    }
    assert summary["by_operation"] == {"UPDATE": 5, "CREATE": 2, "REMOVE": 1}
    assert summary["auto_applied_count"] == 3


def test_summary_empty_input():
    from src.mcp.tools.get_change_history import _build_summary

    summary = _build_summary([])
    assert summary == {
        "total_changes": 0,
        "by_user": {},
        "by_resource_type": {},
        "by_operation": {},
        "auto_applied_count": 0,
    }


@pytest.mark.asyncio
async def test_tool_returns_period_and_rows(monkeypatch):
    """Smoke: tool returns customer_id, period, rows, summary even with empty result."""
    from src.mcp.tools import get_change_history as mod

    async def fake_run_report(**kwargs):
        return []

    monkeypatch.setattr(mod, "run_report", fake_run_report)

    # _resolve_names is async — replace with an async stub returning empty dict
    async def fake_resolve_names(**kwargs):
        return {}

    monkeypatch.setattr(mod, "_resolve_names", fake_resolve_names)

    result = await mod.get_change_history(
        {"customer_id": "1234567890", "date_range": "LAST_7_DAYS"}
    )

    assert result["customer_id"] == "1234567890"
    assert "period" in result
    assert "rows" in result
    assert "summary" in result
    assert result["summary"]["total_changes"] == 0
