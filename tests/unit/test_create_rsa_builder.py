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


def test_builder_preserves_utf8_accents_across_text_fields() -> None:
    """Accented ad copy (ç ã í á ó) is written to the proto byte-for-byte.

    Proto string fields hold native Unicode and serialize as UTF-8 on the gRPC
    wire, so accents MUST survive untouched — there is no ascii-encode /
    accent-strip step in the text path. Guards against a future "fix" that
    normalizes or re-encodes ad text. (2026-07: mojibake like "Loca??o" seen in
    a client console was misread as MCP corruption; the bytes sent to Google
    were always correct — this pins that so it never becomes a doubt again.)
    """
    headlines = ["Locação de Compactador", "Orçamento em Carambeí já", "Serviços Rápidos"]
    descriptions = ["Peça sua cotação à noite.", "Atenção: promoção imperdível!"]
    client = make_capture_client()
    ops = build_create_rsa(
        client,
        "1234567890",
        {
            "rsas": [
                _sample_rsa(
                    headlines=headlines,
                    descriptions=descriptions,
                    path1="Promoção",
                    path2="Serviços",
                )
            ]
        },
    )
    op = ops[0]
    base = "ad_group_ad_operation.create.ad.responsive_search_ad"

    headline_texts = [item.field("text") for item in op._raw(f"{base}.headlines")]
    description_texts = [item.field("text") for item in op._raw(f"{base}.descriptions")]
    assert headline_texts == headlines
    assert description_texts == descriptions
    assert op.field(f"{base}.path1") == "Promoção"
    assert op.field(f"{base}.path2") == "Serviços"
    # ascii-'replace' would inject "?" ("Loca??o"); ascii-'ignore' would drop the
    # char ("Locacao"). The equality asserts above catch both; this makes the
    # "?"-injection case (the exact symptom reported) explicit.
    assert not any("?" in t for t in headline_texts + description_texts)
