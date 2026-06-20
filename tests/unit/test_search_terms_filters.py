"""Filtros server-side no get_search_terms_report + query builder (Onda 3)."""

from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from src.google_ads.queries.tactical import search_terms_query
from src.mcp.tools._registry import get_tool


def test_query_without_filters_omits_metric_clauses() -> None:
    q = search_terms_query(date(2026, 6, 1), date(2026, 6, 19), 50)
    assert "metrics.cost_micros >=" not in q
    assert "metrics.clicks >=" not in q
    assert "metrics.conversions >" not in q
    assert "LIMIT 50" in q


def test_query_with_filters_injects_clauses() -> None:
    q = search_terms_query(
        date(2026, 6, 1),
        date(2026, 6, 19),
        50,
        min_cost_brl=3.0,
        min_clicks=5,
        min_conversions=0,
    )
    assert "metrics.cost_micros >= 3000000" in q
    assert "metrics.clicks >= 5" in q
    assert "metrics.conversions > 0.0" in q


@pytest.mark.asyncio
async def test_handler_passes_filters_into_query(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.mcp.tools.get_search_terms_report as mod

    ctx = MagicMock()
    ctx.manager_id = uuid4()
    ctx.session_id = uuid4()
    monkeypatch.setattr(mod, "get_current", lambda: ctx)

    captured: dict[str, str] = {}

    async def _fake_run_report(**kwargs: object) -> list[object]:
        captured["query"] = str(kwargs["query"])
        return []

    monkeypatch.setattr(mod, "run_report", _fake_run_report)

    tool = get_tool("get_search_terms_report")
    assert tool is not None
    await tool.handler(
        {"customer_id": "1234567890", "date_range": "LAST_7_DAYS", "min_cost_brl": 3.0}
    )
    assert "metrics.cost_micros >= 3000000" in captured["query"]
