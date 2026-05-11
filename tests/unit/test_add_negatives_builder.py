"""Unit tests for build_add_negatives_from_search_terms builder."""

from typing import Any
from unittest.mock import MagicMock

import pytest


def _fake_client() -> MagicMock:
    """Mock SDK client where get_type returns fresh MutateOperation proxies."""
    client = MagicMock()

    # CampaignService.campaign_path returns a path string
    cs = MagicMock()
    cs.campaign_path = lambda cid, camp_id: f"customers/{cid}/campaigns/{camp_id}"
    ags = MagicMock()
    ags.ad_group_path = lambda cid, ag_id: f"customers/{cid}/adGroups/{ag_id}"
    sss = MagicMock()
    sss.shared_set_path = lambda cid, ss_id: f"customers/{cid}/sharedSets/{ss_id}"

    def get_service(name: str) -> Any:
        return {"CampaignService": cs, "AdGroupService": ags, "SharedSetService": sss}[name]

    client.get_service = get_service

    # Track which sub-op fields were touched so tests can assert scope dispatch
    def get_type(_name: str) -> Any:
        m = MagicMock()
        m._touched = {}
        return m

    client.get_type = get_type

    # Match type enum: returns the string identity for assertion
    client.enums.KeywordMatchTypeEnum.__getitem__ = lambda _self, k: k
    return client


@pytest.fixture
def client() -> MagicMock:
    return _fake_client()


def test_builder_dispatches_campaign_scope(client):
    from src.google_ads.mutates.negatives import build_add_negatives_from_search_terms

    payload = {
        "negatives": [
            {
                "search_term": "ruim 1",
                "match_type": "EXACT",
                "scope": "campaign",
                "scope_id": "111",
            },
            {
                "search_term": "ruim 2",
                "match_type": "PHRASE",
                "scope": "campaign",
                "scope_id": "111",
            },
        ]
    }
    ops = build_add_negatives_from_search_terms(client, "1234567890", payload)
    assert len(ops) == 2


def test_builder_dispatches_ad_group_scope(client):
    from src.google_ads.mutates.negatives import build_add_negatives_from_search_terms

    payload = {
        "negatives": [
            {"search_term": "termo", "match_type": "EXACT", "scope": "ad_group", "scope_id": "222"},
        ]
    }
    ops = build_add_negatives_from_search_terms(client, "1234567890", payload)
    assert len(ops) == 1


def test_builder_dispatches_shared_set_scope(client):
    from src.google_ads.mutates.negatives import build_add_negatives_from_search_terms

    payload = {
        "negatives": [
            {
                "search_term": "compartilhada",
                "match_type": "BROAD",
                "scope": "shared_set",
                "scope_id": "333",
            },
        ]
    }
    ops = build_add_negatives_from_search_terms(client, "1234567890", payload)
    assert len(ops) == 1


def test_builder_mixes_scopes_in_single_call(client):
    from src.google_ads.mutates.negatives import build_add_negatives_from_search_terms

    payload = {
        "negatives": [
            {"search_term": "t1", "match_type": "EXACT", "scope": "campaign", "scope_id": "111"},
            {"search_term": "t2", "match_type": "EXACT", "scope": "ad_group", "scope_id": "222"},
            {"search_term": "t3", "match_type": "EXACT", "scope": "shared_set", "scope_id": "333"},
        ]
    }
    ops = build_add_negatives_from_search_terms(client, "1234567890", payload)
    assert len(ops) == 3


def test_builder_rejects_unknown_scope(client):
    from src.google_ads.mutates.negatives import build_add_negatives_from_search_terms

    payload = {
        "negatives": [
            {"search_term": "x", "match_type": "EXACT", "scope": "account", "scope_id": "1"},
        ]
    }
    with pytest.raises((ValueError, KeyError)):
        build_add_negatives_from_search_terms(client, "1234567890", payload)


def test_builder_default_match_type_is_exact(client):
    """Items without match_type field should default to EXACT (per spec §3.2)."""
    from src.google_ads.mutates.negatives import build_add_negatives_from_search_terms

    payload = {
        "negatives": [
            {"search_term": "x", "scope": "campaign", "scope_id": "111"},
        ]
    }
    ops = build_add_negatives_from_search_terms(client, "1234567890", payload)
    assert len(ops) == 1
