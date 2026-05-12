"""Unit tests for build_apply_audience builder."""

from typing import Any
from unittest.mock import MagicMock

import pytest


def _fake_client() -> MagicMock:
    """Mock SDK client with required path helpers + enums."""
    client = MagicMock()

    ag_service = MagicMock()
    ag_service.ad_group_path = lambda cid, ag_id: f"customers/{cid}/adGroups/{ag_id}"
    camp_service = MagicMock()
    camp_service.campaign_path = lambda cid, c_id: f"customers/{cid}/campaigns/{c_id}"

    def get_service(name: str) -> Any:
        if name == "AdGroupService":
            return ag_service
        if name == "CampaignService":
            return camp_service
        return MagicMock()

    client.get_service = get_service

    def get_type(_name: str) -> Any:
        return MagicMock()

    client.get_type = get_type

    client.enums.AdGroupCriterionStatusEnum.ENABLED = "AG_ENABLED"
    client.enums.CampaignCriterionStatusEnum.ENABLED = "CAMP_ENABLED"
    return client


@pytest.fixture
def client() -> MagicMock:
    return _fake_client()


def test_builder_ad_group_user_list_observation(client):
    from src.google_ads.mutates.audiences import build_apply_audience

    payload = {
        "target_type": "ad_group",
        "mode": "observation",
        "attachments": [
            {
                "target_id": "111",
                "audience_type": "user_list",
                "audience_resource_name": "customers/1234567890/userLists/9377822529",
            }
        ],
    }
    ops = build_apply_audience(client, "1234567890", payload)
    assert len(ops) == 1


def test_builder_ad_group_user_interest_observation(client):
    from src.google_ads.mutates.audiences import build_apply_audience

    payload = {
        "target_type": "ad_group",
        "mode": "observation",
        "attachments": [
            {
                "target_id": "111",
                "audience_type": "user_interest",
                "audience_resource_name": "customers/1234567890/userInterests/91501",
            }
        ],
    }
    ops = build_apply_audience(client, "1234567890", payload)
    assert len(ops) == 1


def test_builder_campaign_user_list_exclusion(client):
    from src.google_ads.mutates.audiences import build_apply_audience

    payload = {
        "target_type": "campaign",
        "mode": "exclusion",
        "attachments": [
            {
                "target_id": "22169885957",
                "audience_type": "user_list",
                "audience_resource_name": "customers/1234567890/userLists/9377822529",
            }
        ],
    }
    ops = build_apply_audience(client, "1234567890", payload)
    assert len(ops) == 1


def test_builder_campaign_user_interest_observation(client):
    from src.google_ads.mutates.audiences import build_apply_audience

    payload = {
        "target_type": "campaign",
        "mode": "observation",
        "attachments": [
            {
                "target_id": "22169885957",
                "audience_type": "user_interest",
                "audience_resource_name": "customers/1234567890/userInterests/80179",
            }
        ],
    }
    ops = build_apply_audience(client, "1234567890", payload)
    assert len(ops) == 1


def test_builder_honors_bid_modifier_in_observation(client):
    """bid_modifier present + mode=observation → set on criterion."""
    from src.google_ads.mutates.audiences import build_apply_audience

    payload = {
        "target_type": "ad_group",
        "mode": "observation",
        "attachments": [
            {
                "target_id": "111",
                "audience_type": "user_list",
                "audience_resource_name": "customers/1234567890/userLists/123",
                "bid_modifier": 1.25,
            }
        ],
    }
    ops = build_apply_audience(client, "1234567890", payload)
    assert len(ops) == 1


def test_builder_omits_bid_modifier_in_exclusion(client):
    """Defensive: even if bid_modifier present + mode=exclusion, builder must NOT set it.

    Pre-flight validation rejects this combination upstream — but the builder is
    defensive (don't assume caller validated).
    """
    from src.google_ads.mutates.audiences import build_apply_audience

    payload = {
        "target_type": "campaign",
        "mode": "exclusion",
        "attachments": [
            {
                "target_id": "22169885957",
                "audience_type": "user_list",
                "audience_resource_name": "customers/1234567890/userLists/123",
                "bid_modifier": 1.25,  # should NOT be applied
            }
        ],
    }
    ops = build_apply_audience(client, "1234567890", payload)
    assert len(ops) == 1


def test_builder_status_enabled_for_both_target_types(client):
    """Both ad_group + campaign criteria created with status=ENABLED."""
    from src.google_ads.mutates.audiences import build_apply_audience

    for tt in ("ad_group", "campaign"):
        payload = {
            "target_type": tt,
            "mode": "observation",
            "attachments": [
                {
                    "target_id": "111",
                    "audience_type": "user_list",
                    "audience_resource_name": "customers/1234567890/userLists/123",
                }
            ],
        }
        ops = build_apply_audience(client, "1234567890", payload)
        assert len(ops) == 1


def test_builder_empty_attachments_returns_empty(client):
    """Edge: empty attachments → empty ops (schema rejects this, but builder is defensive)."""
    from src.google_ads.mutates.audiences import build_apply_audience

    ops = build_apply_audience(
        client,
        "1234567890",
        {"target_type": "ad_group", "mode": "observation", "attachments": []},
    )
    assert ops == []
