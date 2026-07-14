"""Unit tests for build_update_rsa (Sprint 3b.18)."""

from __future__ import annotations

from src.google_ads.mutates.ads import build_update_rsa
from tests.unit.fixtures.proto_capture import make_capture_client


def _sample_update(ad_id: str = "100", **overrides):
    return {"ad_id": ad_id, **overrides}


def test_builder_sets_ad_resource_name() -> None:
    """Verify ad.resource_name uses ad_path correctly."""
    client = make_capture_client()
    ops = build_update_rsa(
        client,
        "1234567890",
        {"updates": [_sample_update(headlines=["H1", "H2", "H3"])]},
    )
    assert len(ops) == 1
    op = ops[0]
    assert "customers/1234567890/ads/100" in op.field("ad_operation.update.resource_name")


def test_builder_updates_only_headlines_with_correct_mask() -> None:
    """Only headlines provided → 3 headlines + no other repeated fields touched."""
    client = make_capture_client()
    ops = build_update_rsa(
        client,
        "1234567890",
        {"updates": [_sample_update(headlines=["H1", "H2", "H3"])]},
    )
    op = ops[0]
    assert op.field_count("ad_operation.update.responsive_search_ad.headlines") == 3
    assert op.field_count("ad_operation.update.responsive_search_ad.descriptions") == 0
    # Verify update_mask was accessed (copy_from called on it) — sub-message,
    # so _raw returns the _SubCapture node; not None means it was visited.
    assert op._raw("ad_operation.update_mask") is not None


def test_builder_updates_only_descriptions() -> None:
    """Only descriptions provided → 2 descriptions appended."""
    client = make_capture_client()
    ops = build_update_rsa(
        client,
        "1234567890",
        {"updates": [_sample_update(descriptions=["D1 longer", "D2 also"])]},
    )
    op = ops[0]
    assert op.field_count("ad_operation.update.responsive_search_ad.descriptions") == 2
    assert op.field_count("ad_operation.update.responsive_search_ad.headlines") == 0


def test_builder_updates_only_final_urls() -> None:
    """Only final_urls provided → urls appended on ad (not nested in rsa)."""
    client = make_capture_client()
    ops = build_update_rsa(
        client,
        "1234567890",
        {
            "updates": [
                _sample_update(final_urls=["https://example.com/", "https://example.com/alt"])
            ]
        },
    )
    op = ops[0]
    assert op.field_count("ad_operation.update.final_urls") == 2


def test_builder_updates_only_paths() -> None:
    """path1 + path2 provided → both set on responsive_search_ad."""
    client = make_capture_client()
    ops = build_update_rsa(
        client,
        "1234567890",
        {"updates": [_sample_update(path1="abc", path2="xyz")]},
    )
    op = ops[0]
    assert op.field("ad_operation.update.responsive_search_ad.path1") == "abc"
    assert op.field("ad_operation.update.responsive_search_ad.path2") == "xyz"


def test_builder_updates_all_fields_at_once() -> None:
    """All fields provided → headlines + descriptions + final_urls + path1 + path2 set."""
    client = make_capture_client()
    ops = build_update_rsa(
        client,
        "1234567890",
        {
            "updates": [
                _sample_update(
                    headlines=["H1", "H2", "H3"],
                    descriptions=["D1 longer", "D2 also"],
                    final_urls=["https://example.com/"],
                    path1="abc",
                    path2="xyz",
                )
            ]
        },
    )
    op = ops[0]
    assert op.field_count("ad_operation.update.responsive_search_ad.headlines") == 3
    assert op.field_count("ad_operation.update.responsive_search_ad.descriptions") == 2
    assert op.field_count("ad_operation.update.final_urls") == 1
    assert op.field("ad_operation.update.responsive_search_ad.path1") == "abc"
    assert op.field("ad_operation.update.responsive_search_ad.path2") == "xyz"


def test_builder_preserves_utf8_accents_across_text_fields() -> None:
    """Accented ad copy is written byte-for-byte on update (mirror of create).

    Same guard as test_create_rsa_builder: proto string → UTF-8 on the wire, no
    accent-strip / ascii-encode in build_update_rsa's text path. update_rsa hit
    the same UNACCEPTABLE_SPACING reports as create_rsa, so both are pinned.
    """
    headlines = ["Locação de Compactador", "Orçamento em Carambeí já", "Serviços Rápidos"]
    descriptions = ["Peça sua cotação à noite.", "Atenção: promoção imperdível!"]
    client = make_capture_client()
    ops = build_update_rsa(
        client,
        "1234567890",
        {
            "updates": [
                _sample_update(
                    headlines=headlines,
                    descriptions=descriptions,
                    path1="Promoção",
                    path2="Serviços",
                )
            ]
        },
    )
    op = ops[0]
    base = "ad_operation.update.responsive_search_ad"

    headline_texts = [item.field("text") for item in op._raw(f"{base}.headlines")]
    description_texts = [item.field("text") for item in op._raw(f"{base}.descriptions")]
    assert headline_texts == headlines
    assert description_texts == descriptions
    assert op.field(f"{base}.path1") == "Promoção"
    assert op.field(f"{base}.path2") == "Serviços"
    assert not any("?" in t for t in headline_texts + description_texts)
