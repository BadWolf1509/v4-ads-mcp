"""Unit tests for validate_existing_rsas_for_update (Sprint 3b.18)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from src.google_ads.queries._common import validate_existing_rsas_for_update


@pytest.mark.asyncio
async def test_returns_none_when_all_valid(monkeypatch) -> None:
    """RSA ad em SEARCH campaign ENABLED ad_group → no error."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return [
            {
                "ad_id": "100",
                "ad_type": "RESPONSIVE_SEARCH_AD",
                "ad_group_id": "1",
                "ad_group_name": "AG1",
                "ad_group_status": "ENABLED",
                "campaign_id": "10",
                "campaign_name": "C1",
                "channel_type": "SEARCH",
            }
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_existing_rsas_for_update(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        updates=[{"ad_id": "100", "headlines": ["H1", "H2", "H3"]}],
    )
    assert result is None


@pytest.mark.asyncio
async def test_rejects_missing_ad(monkeypatch) -> None:
    """Ad not in lookup → error."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return []

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_existing_rsas_for_update(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        updates=[{"ad_id": "999", "path1": "abc"}],
    )
    assert result is not None
    assert "999" in result
    assert "nao encontrado" in result.lower()


@pytest.mark.asyncio
async def test_rejects_non_rsa_type(monkeypatch) -> None:
    """ad.type != RESPONSIVE_SEARCH_AD → error mencionando type."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return [
            {
                "ad_id": "100",
                "ad_type": "EXPANDED_TEXT_AD",
                "ad_group_id": "1",
                "ad_group_name": "AG1",
                "ad_group_status": "ENABLED",
                "campaign_id": "10",
                "campaign_name": "C1",
                "channel_type": "SEARCH",
            }
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_existing_rsas_for_update(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        updates=[{"ad_id": "100", "path1": "x"}],
    )
    assert result is not None
    assert "EXPANDED_TEXT_AD" in result
    assert "RESPONSIVE_SEARCH_AD" in result


@pytest.mark.asyncio
async def test_rejects_removed_ad_group(monkeypatch) -> None:
    """Parent ad_group REMOVED → error."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return [
            {
                "ad_id": "100",
                "ad_type": "RESPONSIVE_SEARCH_AD",
                "ad_group_id": "1",
                "ad_group_name": "OldAG",
                "ad_group_status": "REMOVED",
                "campaign_id": "10",
                "campaign_name": "C1",
                "channel_type": "SEARCH",
            }
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_existing_rsas_for_update(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        updates=[{"ad_id": "100", "path1": "x"}],
    )
    assert result is not None
    assert "REMOVED" in result
    assert "OldAG" in result


@pytest.mark.asyncio
async def test_rejects_non_search_channel(monkeypatch) -> None:
    """Parent campaign channel != SEARCH/SEARCH_PARTNERS → error."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return [
            {
                "ad_id": "100",
                "ad_type": "RESPONSIVE_SEARCH_AD",
                "ad_group_id": "1",
                "ad_group_name": "AG1",
                "ad_group_status": "ENABLED",
                "campaign_id": "10",
                "campaign_name": "ShopCamp",
                "channel_type": "SHOPPING",
            }
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_existing_rsas_for_update(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        updates=[{"ad_id": "100", "path1": "x"}],
    )
    assert result is not None
    assert "SHOPPING" in result
    assert "SEARCH" in result
