"""Unit tests for build_bulk_pause builder.

Usa make_capture_client (NÃO MagicMock) pra assertar o oneof correto por
target_type + status=PAUSED + resource_name. bulk_pause_by_query é blast-radius
alto (até 100 entidades); pausar o tipo errado ou setar ENABLED em vez de PAUSED
passaria silenciosamente com MagicMock."""

import pytest

from tests.unit.fixtures.proto_capture import make_capture_client


@pytest.fixture
def client():
    return make_capture_client()


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

    base = "ad_group_criterion_operation.update"
    assert ops[0].field(f"{base}.resource_name") == "customers/1234567890/adGroupCriteria/111~222"
    assert ops[0].field(f"{base}.status") == "PAUSED"  # PAUSED, não ENABLED
    assert ops[1].field(f"{base}.resource_name") == "customers/1234567890/adGroupCriteria/111~333"


def test_builder_dispatches_ad(client):
    from src.google_ads.mutates.bulk import build_bulk_pause

    payload = {"target_type": "ad", "entities": [{"ad_group_id": "111", "ad_id": "222"}]}
    ops = build_bulk_pause(client, "1234567890", payload)
    assert len(ops) == 1

    base = "ad_group_ad_operation.update"
    assert ops[0].field(f"{base}.resource_name") == "customers/1234567890/adGroupAds/111~222"
    assert ops[0].field(f"{base}.status") == "PAUSED"


def test_builder_dispatches_campaign(client):
    from src.google_ads.mutates.bulk import build_bulk_pause

    payload = {
        "target_type": "campaign",
        "entities": [{"campaign_id": "111"}, {"campaign_id": "222"}, {"campaign_id": "333"}],
    }
    ops = build_bulk_pause(client, "1234567890", payload)
    assert len(ops) == 3

    base = "campaign_operation.update"
    assert ops[0].field(f"{base}.resource_name") == "customers/1234567890/campaigns/111"
    assert ops[0].field(f"{base}.status") == "PAUSED"


def test_builder_dispatches_ad_group(client):
    from src.google_ads.mutates.bulk import build_bulk_pause

    payload = {"target_type": "ad_group", "entities": [{"ad_group_id": "111"}]}
    ops = build_bulk_pause(client, "1234567890", payload)
    assert len(ops) == 1

    base = "ad_group_operation.update"
    assert ops[0].field(f"{base}.resource_name") == "customers/1234567890/adGroups/111"
    assert ops[0].field(f"{base}.status") == "PAUSED"


def test_builder_rejects_unknown_target_type(client):
    from src.google_ads.mutates.bulk import build_bulk_pause

    payload = {"target_type": "asset", "entities": [{"asset_id": "111"}]}
    with pytest.raises(ValueError) as e:
        build_bulk_pause(client, "1234567890", payload)
    assert "asset" in str(e.value)
