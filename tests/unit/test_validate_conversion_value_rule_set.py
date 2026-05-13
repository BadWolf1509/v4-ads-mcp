"""Unit tests for validate helpers (Sprint 3b.19B)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from src.google_ads.queries._common import (
    validate_campaign_for_value_rule_set,
    validate_geo_target_constants_for_value_rule,
)


@pytest.mark.asyncio
async def test_validate_campaign_happy_path(monkeypatch) -> None:
    """Campaign exists + status != REMOVED → None."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return [
            {
                "campaign_id": "12345",
                "campaign_name": "Camp1",
                "campaign_status": "ENABLED",
            }
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_campaign_for_value_rule_set(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        campaign_id="12345",
    )
    assert result is None


@pytest.mark.asyncio
async def test_validate_campaign_not_found(monkeypatch) -> None:
    """Empty result → PT-BR error with campaign_id."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return []

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_campaign_for_value_rule_set(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        campaign_id="999",
    )
    assert result is not None
    assert "999" in result
    assert "nao encontrad" in result.lower()


@pytest.mark.asyncio
async def test_validate_campaign_removed_status(monkeypatch) -> None:
    """REMOVED campaign → PT-BR error with name + REMOVED."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return [
            {
                "campaign_id": "12345",
                "campaign_name": "OldCamp",
                "campaign_status": "REMOVED",
            }
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_campaign_for_value_rule_set(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        campaign_id="12345",
    )
    assert result is not None
    assert "OldCamp" in result
    assert "REMOVED" in result


@pytest.mark.asyncio
async def test_validate_geo_targets_happy_path_all_br(monkeypatch) -> None:
    """All geo targets are BR → None."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return [
            {
                "resource_name": "geoTargetConstants/2076",
                "country_code": "BR",
                "name": "Brazil",
            },
            {
                "resource_name": "geoTargetConstants/20114",
                "country_code": "BR",
                "name": "Sao Paulo",
            },
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_geo_target_constants_for_value_rule(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        geo_paths=["geoTargetConstants/2076", "geoTargetConstants/20114"],
    )
    assert result is None


@pytest.mark.asyncio
async def test_validate_geo_targets_first_offender_non_br(monkeypatch) -> None:
    """First non-BR offender (in input order) returns PT-BR error."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return [
            {
                "resource_name": "geoTargetConstants/2840",
                "country_code": "US",
                "name": "United States",
            },
            {
                "resource_name": "geoTargetConstants/2076",
                "country_code": "BR",
                "name": "Brazil",
            },
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_geo_target_constants_for_value_rule(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        geo_paths=["geoTargetConstants/2840", "geoTargetConstants/2076"],
    )
    assert result is not None
    assert "geoTargetConstants/2840" in result
    assert "US" in result
    assert "BR" in result  # mentions expected


@pytest.mark.asyncio
async def test_validate_geo_targets_empty_list_returns_none(monkeypatch) -> None:
    """Defensive: empty list returns None without querying."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        raise AssertionError("run_report should not be called for empty input")

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_geo_target_constants_for_value_rule(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        geo_paths=[],
    )
    assert result is None
