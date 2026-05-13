"""Unit tests for validate_parent_ad_groups_for_rsa_create (Sprint 3b.16)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from src.google_ads.queries._common import validate_parent_ad_groups_for_rsa_create


@pytest.mark.asyncio
async def test_returns_none_when_all_valid(monkeypatch) -> None:
    """SEARCH ad_group ENABLED → no error."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return [
            {
                "ad_group_id": "1",
                "ad_group_name": "AG1",
                "ad_group_status": "ENABLED",
                "campaign_id": "100",
                "campaign_name": "C1",
                "channel_type": "SEARCH",
            }
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_parent_ad_groups_for_rsa_create(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        rsas=[{"ad_group_id": "1"}],
    )
    assert result is None


@pytest.mark.asyncio
async def test_rejects_missing_ad_group(monkeypatch) -> None:
    """ad_group not in lookup → error."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return []

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_parent_ad_groups_for_rsa_create(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        rsas=[{"ad_group_id": "999"}],
    )
    assert result is not None
    assert "999" in result
    assert "nao encontrado" in result.lower()


@pytest.mark.asyncio
async def test_rejects_removed_ad_group(monkeypatch) -> None:
    """REMOVED ad_group → error."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return [
            {
                "ad_group_id": "1",
                "ad_group_name": "OldAG",
                "ad_group_status": "REMOVED",
                "campaign_id": "100",
                "campaign_name": "C1",
                "channel_type": "SEARCH",
            }
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_parent_ad_groups_for_rsa_create(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        rsas=[{"ad_group_id": "1"}],
    )
    assert result is not None
    assert "REMOVED" in result
    assert "OldAG" in result


@pytest.mark.asyncio
async def test_rejects_non_search_channel(monkeypatch) -> None:
    """ad_group in SHOPPING campaign → error mencionando RSA SEARCH-only."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return [
            {
                "ad_group_id": "1",
                "ad_group_name": "ShopAG",
                "ad_group_status": "ENABLED",
                "campaign_id": "100",
                "campaign_name": "ShopCamp",
                "channel_type": "SHOPPING",
            }
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_parent_ad_groups_for_rsa_create(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        rsas=[{"ad_group_id": "1"}],
    )
    assert result is not None
    assert "SHOPPING" in result
    assert "SEARCH" in result


@pytest.mark.asyncio
async def test_handles_batch_with_multiple_ad_groups(monkeypatch) -> None:
    """3 RSAs across 2 ad_groups (one bad) → first offender returned."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return [
            {
                "ad_group_id": "1",
                "ad_group_name": "Good",
                "ad_group_status": "ENABLED",
                "campaign_id": "100",
                "campaign_name": "C1",
                "channel_type": "SEARCH",
            },
            {
                "ad_group_id": "2",
                "ad_group_name": "Bad",
                "ad_group_status": "REMOVED",
                "campaign_id": "101",
                "campaign_name": "C2",
                "channel_type": "SEARCH",
            },
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_parent_ad_groups_for_rsa_create(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        rsas=[{"ad_group_id": "1"}, {"ad_group_id": "2"}, {"ad_group_id": "1"}],
    )
    assert result is not None
    assert "Bad" in result
    assert "REMOVED" in result
