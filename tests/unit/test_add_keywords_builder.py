"""Unit tests for build_add_keywords builder."""

from typing import Any
from unittest.mock import MagicMock

import pytest


def _fake_client() -> MagicMock:
    """Mock SDK client with required path helpers + enums."""
    client = MagicMock()

    ag_service = MagicMock()
    ag_service.ad_group_path = lambda cid, ag_id: f"customers/{cid}/adGroups/{ag_id}"
    client.get_service = MagicMock(return_value=ag_service)

    # Return a fresh MutateOperation proxy per call so attribute writes don't bleed
    def get_type(_name: str) -> Any:
        return MagicMock()

    client.get_type = get_type

    # Match type enum: lookups return identity strings
    client.enums.KeywordMatchTypeEnum.__getitem__ = lambda _self, k: k
    client.enums.AdGroupCriterionStatusEnum.ENABLED = "ENABLED"
    return client


@pytest.fixture
def client() -> MagicMock:
    return _fake_client()


def test_builder_emits_one_op_per_keyword(client):
    from src.google_ads.mutates.keywords import build_add_keywords

    payload = {
        "ad_group_id": "111",
        "keywords": [
            {"text": "nutricionista jp", "match_type": "EXACT"},
            {"text": "nutricionista esportiva", "match_type": "PHRASE"},
        ],
    }
    ops = build_add_keywords(client, "1234567890", payload)
    assert len(ops) == 2


def test_builder_supports_optional_cpc_bid_micros(client):
    from src.google_ads.mutates.keywords import build_add_keywords

    payload = {
        "ad_group_id": "111",
        "keywords": [
            {"text": "kw com bid", "match_type": "EXACT", "cpc_bid_micros": 2000000},
            {"text": "kw sem bid", "match_type": "PHRASE"},
        ],
    }
    ops = build_add_keywords(client, "1234567890", payload)
    assert len(ops) == 2


def test_builder_match_type_case_normalized(client):
    """match_type 'exact' (lowercase) is normalized to 'EXACT'."""
    from src.google_ads.mutates.keywords import build_add_keywords

    payload = {
        "ad_group_id": "111",
        "keywords": [{"text": "x", "match_type": "exact"}],
    }
    # Should not raise — case-insensitive lookup via .upper()
    ops = build_add_keywords(client, "1234567890", payload)
    assert len(ops) == 1


def test_builder_empty_list_returns_empty(client):
    """Edge: empty keywords array → empty ops list (schema rejects this, but builder is defensive)."""
    from src.google_ads.mutates.keywords import build_add_keywords

    ops = build_add_keywords(client, "1234567890", {"ad_group_id": "111", "keywords": []})
    assert ops == []
