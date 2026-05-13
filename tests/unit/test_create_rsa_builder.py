"""Unit tests for build_create_rsa (Sprint 3b.16)."""

from __future__ import annotations

from src.google_ads.mutates.ads import build_create_rsa
from tests.unit.fixtures.proto_capture import make_capture_client


def _sample_rsa(ad_group_id: str = "100", **overrides):
    base = {
        "ad_group_id": ad_group_id,
        "headlines": ["H1", "H2", "H3", "H4", "H5"],
        "descriptions": ["D1 longer text", "D2 another desc"],
        "final_urls": ["https://example.com/"],
    }
    base.update(overrides)
    return base


def test_builder_sets_ad_group_path_and_status() -> None:
    """Single RSA: verify ad_group path + status set correctly."""
    client = make_capture_client()
    ops = build_create_rsa(client, "1234567890", {"rsas": [_sample_rsa()]})
    assert len(ops) == 1
    op = ops[0]
    assert "customers/1234567890/adGroups/100" in op.field("ad_group_ad_operation.create.ad_group")
    assert op.has("ad_group_ad_operation.create.status") is True


def test_builder_adds_all_headlines() -> None:
    """5 headlines → all 5 added to responsive_search_ad."""
    client = make_capture_client()
    ops = build_create_rsa(client, "1234567890", {"rsas": [_sample_rsa()]})
    op = ops[0]
    headlines_count = op.field_count(
        "ad_group_ad_operation.create.ad.responsive_search_ad.headlines"
    )
    assert headlines_count == 5


def test_builder_adds_all_descriptions() -> None:
    """2 descriptions → both added."""
    client = make_capture_client()
    ops = build_create_rsa(client, "1234567890", {"rsas": [_sample_rsa()]})
    op = ops[0]
    desc_count = op.field_count("ad_group_ad_operation.create.ad.responsive_search_ad.descriptions")
    assert desc_count == 2


def test_builder_adds_final_urls() -> None:
    """final_urls populated on ad."""
    client = make_capture_client()
    ops = build_create_rsa(
        client,
        "1234567890",
        {"rsas": [_sample_rsa(final_urls=["https://example.com/", "https://example.com/alt"])]},
    )
    op = ops[0]
    urls_count = op.field_count("ad_group_ad_operation.create.ad.final_urls")
    assert urls_count == 2


def test_builder_omits_path1_path2_when_not_provided() -> None:
    """Without path1/path2, fields NOT set."""
    client = make_capture_client()
    ops = build_create_rsa(client, "1234567890", {"rsas": [_sample_rsa()]})
    op = ops[0]
    assert op.has("ad_group_ad_operation.create.ad.responsive_search_ad.path1") is False
    assert op.has("ad_group_ad_operation.create.ad.responsive_search_ad.path2") is False


def test_builder_creates_n_operations_for_batch() -> None:
    """Batch of 3 RSAs → 3 operations."""
    client = make_capture_client()
    ops = build_create_rsa(
        client,
        "1234567890",
        {"rsas": [_sample_rsa("100"), _sample_rsa("101"), _sample_rsa("100")]},
    )
    assert len(ops) == 3
