"""Unit tests for validate_parent_campaigns_for_ad_group_create (Sprint 3b.14)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from src.google_ads.queries._common import validate_parent_campaigns_for_ad_group_create


@pytest.mark.asyncio
async def test_returns_none_when_all_campaigns_valid(monkeypatch) -> None:
    """Valid SEARCH campaign + matching SEARCH_STANDARD ad_group → no error."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return [
            {
                "campaign_id": "100",
                "campaign_name": "C1",
                "status": "ENABLED",
                "channel_type": "SEARCH",
                "strategy": "MAXIMIZE_CONVERSIONS",
            },
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_parent_campaigns_for_ad_group_create(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        ad_groups=[{"campaign_id": "100", "name": "AG1", "type": "SEARCH_STANDARD"}],
    )
    assert result is None


@pytest.mark.asyncio
async def test_rejects_missing_campaign(monkeypatch) -> None:
    """Campaign not in lookup result → error mentions campaign_id."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return []

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_parent_campaigns_for_ad_group_create(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        ad_groups=[{"campaign_id": "999", "name": "AG1"}],
    )
    assert result is not None
    assert "999" in result
    assert "nao encontrada" in result.lower()


@pytest.mark.asyncio
async def test_rejects_removed_campaign(monkeypatch) -> None:
    """REMOVED campaign → error mentions REMOVED."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return [
            {
                "campaign_id": "100",
                "campaign_name": "OldCamp",
                "status": "REMOVED",
                "channel_type": "SEARCH",
                "strategy": "MAXIMIZE_CONVERSIONS",
            },
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_parent_campaigns_for_ad_group_create(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        ad_groups=[{"campaign_id": "100", "name": "AG1"}],
    )
    assert result is not None
    assert "REMOVED" in result
    assert "OldCamp" in result


@pytest.mark.asyncio
async def test_rejects_channel_mismatch(monkeypatch) -> None:
    """SHOPPING_PRODUCT_ADS in SEARCH campaign → error."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return [
            {
                "campaign_id": "100",
                "campaign_name": "SearchCamp",
                "status": "ENABLED",
                "channel_type": "SEARCH",
                "strategy": "MAXIMIZE_CONVERSIONS",
            },
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_parent_campaigns_for_ad_group_create(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        ad_groups=[{"campaign_id": "100", "name": "AG1", "type": "SHOPPING_PRODUCT_ADS"}],
    )
    assert result is not None
    assert "SHOPPING_PRODUCT_ADS" in result
    assert "SEARCH" in result


@pytest.mark.asyncio
async def test_rejects_cpc_bid_in_auto_bidding(monkeypatch) -> None:
    """F12 lesson: cpc_bid_micros in auto-bidding campaign → error."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return [
            {
                "campaign_id": "100",
                "campaign_name": "AutoBidCamp",
                "status": "ENABLED",
                "channel_type": "SEARCH",
                "strategy": "MAXIMIZE_CONVERSIONS",
            },
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_parent_campaigns_for_ad_group_create(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        ad_groups=[
            {
                "campaign_id": "100",
                "name": "AG1",
                "cpc_bid_micros": 1_000_000,
            }
        ],
    )
    assert result is not None
    assert "cpc_bid_micros" in result
    assert "MAXIMIZE_CONVERSIONS" in result
