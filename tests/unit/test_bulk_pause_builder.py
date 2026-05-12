"""Unit tests for build_bulk_pause builder."""

from typing import Any
from unittest.mock import MagicMock

import pytest


def _fake_client() -> MagicMock:
    """Mock SDK client with required service path helpers."""
    client = MagicMock()

    cs = MagicMock()
    cs.campaign_path = lambda cid, camp_id: f"customers/{cid}/campaigns/{camp_id}"
    ags = MagicMock()
    ags.ad_group_path = lambda cid, ag_id: f"customers/{cid}/adGroups/{ag_id}"
    aads = MagicMock()
    aads.ad_group_ad_path = lambda cid, ag_id, ad_id: f"customers/{cid}/adGroupAds/{ag_id}~{ad_id}"
    crit = MagicMock()
    crit.ad_group_criterion_path = lambda cid, ag_id, c_id: (
        f"customers/{cid}/adGroupCriteria/{ag_id}~{c_id}"
    )

    def get_service(name: str) -> Any:
        return {
            "CampaignService": cs,
            "AdGroupService": ags,
            "AdGroupAdService": aads,
            "AdGroupCriterionService": crit,
        }[name]

    client.get_service = get_service

    def get_type(_name: str) -> Any:
        return MagicMock()

    client.get_type = get_type

    # Stub all four status enums
    client.enums.AdGroupCriterionStatusEnum.PAUSED = "PAUSED"
    client.enums.AdGroupAdStatusEnum.PAUSED = "PAUSED"
    client.enums.CampaignStatusEnum.PAUSED = "PAUSED"
    client.enums.AdGroupStatusEnum.PAUSED = "PAUSED"

    client.copy_from = MagicMock()
    return client


@pytest.fixture
def client() -> MagicMock:
    return _fake_client()


def test_builder_dispatches_keyword(client):
    from src.google_ads.mutates.bulk import build_bulk_pause

    payload = {
        "target_type": "keyword",
        "entities": [
            {"ad_group_id": "111", "criterion_id": "222"},
            {"ad_group_id": "111", "criterion_id": "333"},
        ],
    }
    ops = build_bulk_pause(client, "1234567890", payload)
    assert len(ops) == 2


def test_builder_dispatches_ad(client):
    from src.google_ads.mutates.bulk import build_bulk_pause

    payload = {
        "target_type": "ad",
        "entities": [{"ad_group_id": "111", "ad_id": "222"}],
    }
    ops = build_bulk_pause(client, "1234567890", payload)
    assert len(ops) == 1


def test_builder_dispatches_campaign(client):
    from src.google_ads.mutates.bulk import build_bulk_pause

    payload = {
        "target_type": "campaign",
        "entities": [{"campaign_id": "111"}, {"campaign_id": "222"}, {"campaign_id": "333"}],
    }
    ops = build_bulk_pause(client, "1234567890", payload)
    assert len(ops) == 3


def test_builder_dispatches_ad_group(client):
    from src.google_ads.mutates.bulk import build_bulk_pause

    payload = {
        "target_type": "ad_group",
        "entities": [{"ad_group_id": "111"}],
    }
    ops = build_bulk_pause(client, "1234567890", payload)
    assert len(ops) == 1


def test_builder_rejects_unknown_target_type(client):
    from src.google_ads.mutates.bulk import build_bulk_pause

    payload = {
        "target_type": "asset",  # not supported
        "entities": [{"asset_id": "111"}],
    }
    with pytest.raises(ValueError) as e:
        build_bulk_pause(client, "1234567890", payload)
    assert "asset" in str(e.value)
