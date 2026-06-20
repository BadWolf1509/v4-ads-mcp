"""Os 8 reports consolidados pela 2A devem passar audit_this_call=True (gate da Fase 2B)."""

from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from src.mcp.tools._registry import get_tool

# (módulo do tool, nome registrado)
_REPORTS = [
    ("src.mcp.tools.get_campaign_performance", "get_campaign_performance"),
    ("src.mcp.tools.get_ad_group_performance", "get_ad_group_performance"),
    ("src.mcp.tools.get_ad_performance", "get_ad_performance"),
    ("src.mcp.tools.get_keyword_performance", "get_keyword_performance"),
    ("src.mcp.tools.get_audience_performance", "get_audience_performance"),
    ("src.mcp.tools.get_device_performance", "get_device_performance"),
    ("src.mcp.tools.get_geo_performance", "get_geo_performance"),
    ("src.mcp.tools.get_hourly_performance", "get_hourly_performance"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("module_path, tool_name", _REPORTS)
async def test_report_opts_into_audit(
    module_path: str, tool_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib

    mod = importlib.import_module(module_path)

    ctx = MagicMock()
    ctx.manager_id = uuid4()
    ctx.session_id = uuid4()
    monkeypatch.setattr(mod, "get_current", lambda: ctx)

    captured: dict[str, Any] = {}

    async def _fake_run_report(**kwargs: Any) -> list[Any]:
        captured.update(kwargs)
        return []

    monkeypatch.setattr(mod, "run_report", _fake_run_report)

    tool = get_tool(tool_name)
    assert tool is not None
    await tool.handler({"customer_id": "1234567890", "date_range": "LAST_7_DAYS"})

    assert captured.get("audit_this_call") is True, f"{tool_name} não opta por audit_this_call"
