"""Unit tests for validate_manual_cpc_strategy helper (Sprint 3b.8 F12 fix)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from src.google_ads.queries._common import validate_manual_cpc_strategy


@pytest.mark.asyncio
async def test_returns_none_for_empty_ad_group_ids() -> None:
    """Empty list → skip GAQL, return None early."""
    result = await validate_manual_cpc_strategy(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        ad_group_ids=[],
    )
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_when_all_manual_cpc(monkeypatch: pytest.MonkeyPatch) -> None:
    """All campaigns in MANUAL_CPC → no rejection."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return [
            {
                "ad_group_id": "1",
                "campaign_id": "100",
                "campaign_name": "Camp1",
                "strategy": "MANUAL_CPC",
            },
            {
                "ad_group_id": "2",
                "campaign_id": "101",
                "campaign_name": "Camp2",
                "strategy": "MANUAL_CPC",
            },
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_manual_cpc_strategy(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        ad_group_ids=["1", "2"],
    )
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_when_all_enhanced_cpc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ENHANCED_CPC (legacy) also in whitelist → no rejection."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return [
            {
                "ad_group_id": "1",
                "campaign_id": "100",
                "campaign_name": "LegacyCamp",
                "strategy": "ENHANCED_CPC",
            },
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_manual_cpc_strategy(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        ad_group_ids=["1"],
    )
    assert result is None


@pytest.mark.asyncio
async def test_rejects_mixed_batch_with_first_offender(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mixed: 1 MANUAL_CPC + 1 MAXIMIZE_CONVERSIONS → error mentioning the bad one."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return [
            {
                "ad_group_id": "1",
                "campaign_id": "100",
                "campaign_name": "Manual",
                "strategy": "MANUAL_CPC",
            },
            {
                "ad_group_id": "2",
                "campaign_id": "101",
                "campaign_name": "AutoBid",
                "strategy": "MAXIMIZE_CONVERSIONS",
            },
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_manual_cpc_strategy(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        ad_group_ids=["1", "2"],
    )
    assert result is not None
    assert "MAXIMIZE_CONVERSIONS" in result
    assert "AutoBid" in result
    assert "101" in result


@pytest.mark.asyncio
async def test_rejects_when_target_cpa(monkeypatch: pytest.MonkeyPatch) -> None:
    """TARGET_CPA → rejection with strategy name + 'ignorados' or 'silenciosamente' in error."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return [
            {
                "ad_group_id": "1",
                "campaign_id": "100",
                "campaign_name": "TargetCpaCamp",
                "strategy": "TARGET_CPA",
            },
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_manual_cpc_strategy(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        ad_group_ids=["1"],
    )
    assert result is not None
    assert "TARGET_CPA" in result
    error_lower = result.lower()
    assert (
        "silent-failure" in error_lower
        or "silenciosamente" in error_lower
        or "ignorados" in error_lower
    )
