"""Integration tests for detect_drift (Sprint 3b.33)."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current


@pytest.fixture
def bound_context():
    ctx = McpRequestContext(manager_id=uuid4(), session_id=uuid4())
    set_current(ctx)
    yield ctx
    clear_current()


@pytest.mark.asyncio
async def test_co_management_filter_pedro_drift(bound_context):
    """T2 cenário smoke: 2 changes Wellington autorizado + 4 Pedro Vytor drift."""
    from src.mcp.tools.detect_drift import detect_drift

    fake_history_result = {
        "customer_id": "7862230676",
        "period": {"from": "2026-05-20", "to": "2026-05-21"},
        "rows": [
            {
                "change_date_time": "2026-05-21 14:30:00",
                "user_email": "wellinton.ribeiro@v4company.com",
                "client_type": "GOOGLE_ADS_WEB_CLIENT",
                "resource_type": "CAMPAIGN",
                "resource_id": "22169885957",
                "resource_name": "CAB - Geral",
                "operation": "UPDATE",
                "changed_fields": ["campaign.text_guidelines.messaging_restrictions"],
                "campaign_id": "22169885957",
                "ad_group_id": None,
            },
            {
                "change_date_time": "2026-05-20 10:13:00",
                "user_email": "pedro.vytor@v4company.com",
                "client_type": "GOOGLE_ADS_WEB_CLIENT",
                "resource_type": "CAMPAIGN",
                "resource_id": "22169885957",
                "resource_name": "CAB - Geral",
                "operation": "UPDATE",
                "changed_fields": ["campaign.ai_max_setting.enable_ai_max"],
                "campaign_id": "22169885957",
                "ad_group_id": None,
            },
            {
                "change_date_time": "2026-05-20 10:12:30",
                "user_email": "pedro.vytor@v4company.com",
                "client_type": "GOOGLE_ADS_WEB_CLIENT",
                "resource_type": "CAMPAIGN",
                "resource_id": "21359547724",
                "resource_name": "JPA - Geral",
                "operation": "UPDATE",
                "changed_fields": ["campaign.ai_max_setting.enable_ai_max"],
                "campaign_id": "21359547724",
                "ad_group_id": None,
            },
        ],
        "summary": {},
    }
    with patch(
        "src.mcp.tools.detect_drift.get_change_history",
        AsyncMock(return_value=fake_history_result),
    ):
        result = await detect_drift(
            {
                "customer_id": "7862230676",
                "responsible_user_emails": ["wellinton.ribeiro@v4company.com"],
                "date_range": "LAST_2_DAYS",
            }
        )
    assert result["summary"]["total_drift_changes"] == 2
    assert result["summary"]["total_changes_in_window"] == 3
    assert result["summary"]["by_user"] == {"pedro.vytor@v4company.com": 2}
    assert result["returned_count"] == 2


@pytest.mark.asyncio
async def test_incident_mode_empty_responsible_list(bound_context):
    """T1 cenário smoke: lista vazia → todos changes são drift."""
    from src.mcp.tools.detect_drift import detect_drift

    fake_history_result = {
        "customer_id": "7862230676",
        "period": {"from": "2026-05-19", "to": "2026-05-21"},
        "rows": [
            {
                "change_date_time": "2026-05-20 10:13:00",
                "user_email": "anyone@v4.com",
                "client_type": "GOOGLE_ADS_WEB_CLIENT",
                "resource_type": "CAMPAIGN",
                "resource_id": "22169885957",
                "resource_name": "CAB",
                "operation": "UPDATE",
                "changed_fields": ["campaign.status"],
                "campaign_id": "22169885957",
                "ad_group_id": None,
            }
        ],
        "summary": {},
    }
    with patch(
        "src.mcp.tools.detect_drift.get_change_history",
        AsyncMock(return_value=fake_history_result),
    ):
        result = await detect_drift({"customer_id": "7862230676"})
    assert result["summary"]["total_drift_changes"] == 1
    assert result["responsible_user_emails"] == []


@pytest.mark.asyncio
async def test_structural_change_flag_emitted(bound_context):
    """T5 cenário smoke: REMOVE em CAMPAIGN → structural_change flag."""
    from src.mcp.tools.detect_drift import detect_drift

    fake_history_result = {
        "customer_id": "7862230676",
        "period": {"from": "2026-05-19", "to": "2026-05-21"},
        "rows": [
            {
                "change_date_time": "2026-05-20 10:13:00",
                "user_email": "intruso@external.com",
                "client_type": "GOOGLE_ADS_WEB_CLIENT",
                "resource_type": "CAMPAIGN",
                "resource_id": "22169885957",
                "resource_name": "CAB",
                "operation": "REMOVE",
                "changed_fields": [],
                "campaign_id": "22169885957",
                "ad_group_id": None,
            }
        ],
        "summary": {},
    }
    with patch(
        "src.mcp.tools.detect_drift.get_change_history",
        AsyncMock(return_value=fake_history_result),
    ):
        result = await detect_drift({"customer_id": "7862230676"})
    flag_codes = [f["code"] for f in result["flags"]]
    assert "structural_change" in flag_codes
    structural_flag = next(f for f in result["flags"] if f["code"] == "structural_change")
    assert structural_flag["severity"] == "high"
