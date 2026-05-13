"""Unit tests for build_create_ad_group (Sprint 3b.14)."""

from __future__ import annotations

from src.google_ads.mutates.ad_groups import build_create_ad_group
from tests.unit.fixtures.proto_capture import make_capture_client


def test_builder_sets_name_and_campaign_path() -> None:
    """Single ad_group: verify name, campaign resource_name, type, status set correctly."""
    client = make_capture_client()
    ops = build_create_ad_group(
        client,
        "1234567890",
        {
            "ad_groups": [
                {
                    "campaign_id": "100",
                    "name": "Test AG",
                    "type": "SEARCH_STANDARD",
                    "status": "PAUSED",
                }
            ]
        },
    )
    assert len(ops) == 1
    op = ops[0]
    assert op.field("ad_group_operation.create.name") == "Test AG"
    assert "customers/1234567890/campaigns/100" in op.field("ad_group_operation.create.campaign")


def test_builder_defaults_type_to_search_standard_and_status_to_paused() -> None:
    """Without explicit type/status, defaults applied (type=SEARCH_STANDARD, status=PAUSED)."""
    client = make_capture_client()
    ops = build_create_ad_group(
        client,
        "1234567890",
        {"ad_groups": [{"campaign_id": "100", "name": "AG"}]},
    )
    op = ops[0]
    assert op.has("ad_group_operation.create.type_") is True
    assert op.has("ad_group_operation.create.status") is True


def test_builder_omits_cpc_bid_when_not_provided() -> None:
    """F12 prevention: cpc_bid_micros NOT set if not in payload."""
    client = make_capture_client()
    ops = build_create_ad_group(
        client,
        "1234567890",
        {"ad_groups": [{"campaign_id": "100", "name": "AG"}]},
    )
    op = ops[0]
    assert op.has("ad_group_operation.create.cpc_bid_micros") is False


def test_builder_sets_cpc_bid_when_provided() -> None:
    """When cpc_bid_micros provided, set on the proto."""
    client = make_capture_client()
    ops = build_create_ad_group(
        client,
        "1234567890",
        {"ad_groups": [{"campaign_id": "100", "name": "AG", "cpc_bid_micros": 1_500_000}]},
    )
    op = ops[0]
    assert op.field("ad_group_operation.create.cpc_bid_micros") == 1_500_000


def test_builder_creates_n_operations_for_batch() -> None:
    """Batch of 3 ad_groups → 3 operations returned."""
    client = make_capture_client()
    ops = build_create_ad_group(
        client,
        "1234567890",
        {
            "ad_groups": [
                {"campaign_id": "100", "name": "AG1"},
                {"campaign_id": "101", "name": "AG2"},
                {"campaign_id": "100", "name": "AG3"},
            ]
        },
    )
    assert len(ops) == 3
