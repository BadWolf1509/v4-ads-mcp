"""Unit tests for validate_conversion_action_create (Sprint 3b.19A)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from src.google_ads.queries._common import validate_conversion_action_create


@pytest.mark.asyncio
async def test_returns_none_when_all_names_unique(monkeypatch) -> None:
    """No existing names match → no error."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return []  # No matches

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_conversion_action_create(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        actions=[
            {"name": "Lead WhatsApp", "category": "SUBMIT_LEAD_FORM", "type": "WEBPAGE"},
            {"name": "Compra Checkout", "category": "PURCHASE", "type": "WEBPAGE"},
        ],
    )
    assert result is None


@pytest.mark.asyncio
async def test_rejects_single_duplicate_name(monkeypatch) -> None:
    """One existing name matches → first-offender error PT-BR."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return [{"conversion_action_name": "Lead WhatsApp"}]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_conversion_action_create(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        actions=[{"name": "Lead WhatsApp", "category": "SUBMIT_LEAD_FORM", "type": "WEBPAGE"}],
    )
    assert result is not None
    assert "Lead WhatsApp" in result
    assert "ja existe" in result.lower()


@pytest.mark.asyncio
async def test_rejects_first_offender_when_multiple_duplicates(monkeypatch) -> None:
    """Multiple duplicates → returns first in input order (deterministic)."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return [
            {"conversion_action_name": "Compra Checkout"},
            {"conversion_action_name": "Lead WhatsApp"},
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_conversion_action_create(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        actions=[
            {"name": "Lead WhatsApp", "category": "SUBMIT_LEAD_FORM", "type": "WEBPAGE"},
            {"name": "Compra Checkout", "category": "PURCHASE", "type": "WEBPAGE"},
        ],
    )
    assert result is not None
    # First in INPUT order should be reported even though GAQL may return in any order
    assert "Lead WhatsApp" in result


@pytest.mark.asyncio
async def test_empty_list_returns_none(monkeypatch) -> None:
    """Defensive: empty actions list returns None without querying."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        raise AssertionError("run_report should not be called for empty input")

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_conversion_action_create(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        actions=[],
    )
    assert result is None


@pytest.mark.asyncio
async def test_gaql_exception_propagates(monkeypatch) -> None:
    """Errors from run_report bubble up (let caller handle)."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        raise RuntimeError("GAQL boom")

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    with pytest.raises(RuntimeError, match="GAQL boom"):
        await validate_conversion_action_create(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            actions=[{"name": "X", "category": "SUBMIT_LEAD_FORM", "type": "WEBPAGE"}],
        )
