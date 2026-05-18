"""Unit tests for build_create_and_link_assets (Sprint 3b.25).

Builder tests use ProtoFieldCapture (post-Sprint 3b.5 convention) to verify
proto field assignments. MagicMock would mask bugs like A4 (Google override
of negative=True) — see findings-catalog §A4.
"""

from __future__ import annotations

from tests.unit.fixtures.proto_capture import make_capture_client


def _payload_with_assets(assets):
    return {"customer_id": "1234567890", "assets": assets}


def _sitelink_minimal():
    return {
        "type": "SITELINK",
        "attachment_level": "CAMPAIGN",
        "attachment_id": "customers/1234567890/campaigns/99999",
        "link_text": "Sobre",
        "final_urls": ["https://example.com/sobre"],
    }


# ============================================================================
# Per-type happy path (5 tests)
# ============================================================================


def test_builder_sitelink_minimal_sets_link_text_and_final_urls():
    from src.google_ads.mutates.assets import build_create_and_link_assets

    client = make_capture_client()
    ops = build_create_and_link_assets(
        client, "1234567890", _payload_with_assets([_sitelink_minimal()])
    )

    assert len(ops) == 2  # 1 asset + 1 link

    asset_op = ops[0]
    assert (
        asset_op.field("asset_operation.create.resource_name") == "customers/1234567890/assets/-1"
    )
    assert asset_op.field("asset_operation.create.sitelink_asset.link_text") == "Sobre"
    assert asset_op.field_count("asset_operation.create.final_urls") == 1


def test_builder_sitelink_with_descriptions_sets_both_lines():
    from src.google_ads.mutates.assets import build_create_and_link_assets

    asset = _sitelink_minimal()
    asset["description1"] = "Linha 1"
    asset["description2"] = "Linha 2"

    client = make_capture_client()
    ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets([asset]))

    asset_op = ops[0]
    assert asset_op.field("asset_operation.create.sitelink_asset.description1") == "Linha 1"
    assert asset_op.field("asset_operation.create.sitelink_asset.description2") == "Linha 2"


def test_builder_callout_sets_callout_text():
    from src.google_ads.mutates.assets import build_create_and_link_assets

    asset = {
        "type": "CALLOUT",
        "attachment_level": "CAMPAIGN",
        "attachment_id": "customers/1234567890/campaigns/99999",
        "callout_text": "Atendimento 24h",
    }
    client = make_capture_client()
    ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets([asset]))

    asset_op = ops[0]
    assert asset_op.field("asset_operation.create.callout_asset.callout_text") == "Atendimento 24h"


def test_builder_structured_snippet_sets_header_and_values():
    from src.google_ads.mutates.assets import build_create_and_link_assets

    asset = {
        "type": "STRUCTURED_SNIPPET",
        "attachment_level": "CAMPAIGN",
        "attachment_id": "customers/1234567890/campaigns/99999",
        "header": "Catálogo de serviços",  # F38 Sprint 3b.25.1: PT-BR display string
        "values": ["SEO", "Mídia Paga", "Branding"],
    }
    client = make_capture_client()
    ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets([asset]))

    asset_op = ops[0]
    assert (
        asset_op.field("asset_operation.create.structured_snippet_asset.header")
        == "Catálogo de serviços"
    )
    assert asset_op.field_count("asset_operation.create.structured_snippet_asset.values") == 3


def test_builder_call_sets_phone_and_country_code_br():
    """V4 invariant assertion — country_code MUST be hardcoded BR."""
    from src.google_ads.mutates.assets import build_create_and_link_assets

    asset = {
        "type": "CALL",
        "attachment_level": "CAMPAIGN",
        "attachment_id": "customers/1234567890/campaigns/99999",
        "phone_number": "(11) 98765-4321",
    }
    client = make_capture_client()
    ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets([asset]))

    asset_op = ops[0]
    assert asset_op.field("asset_operation.create.call_asset.phone_number") == "(11) 98765-4321"
    assert asset_op.field("asset_operation.create.call_asset.country_code") == "BR"


# ============================================================================
# PROMOTION variants (3 tests)
# ============================================================================


def test_builder_promotion_percent_off_sets_micros_with_10000_factor():
    """F-class regression: percent_off micros formula is value * 10_000 (1M = 100%)."""
    from src.google_ads.mutates.assets import build_create_and_link_assets

    asset = {
        "type": "PROMOTION",
        "attachment_level": "CAMPAIGN",
        "attachment_id": "customers/1234567890/campaigns/99999",
        "promotion_target": "Verão 2026",
        "discount_modifier": "UP_TO",
        "percent_off": 20.0,
        "final_urls": ["https://example.com/promo"],
    }
    client = make_capture_client()
    ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets([asset]))

    asset_op = ops[0]
    # 20.0 percent → 200_000 micros (NOT 20_000_000)
    assert asset_op.field("asset_operation.create.promotion_asset.percent_off") == 200_000


def test_builder_promotion_money_amount_off_sets_amount_micros_and_brl():
    """V4 invariant: currency_code hardcoded BRL."""
    from src.google_ads.mutates.assets import build_create_and_link_assets

    asset = {
        "type": "PROMOTION",
        "attachment_level": "CAMPAIGN",
        "attachment_id": "customers/1234567890/campaigns/99999",
        "promotion_target": "Verão 2026",
        "discount_modifier": "NONE",
        "money_amount_off_brl": 50.0,
        "final_urls": ["https://example.com/promo"],
    }
    client = make_capture_client()
    ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets([asset]))

    asset_op = ops[0]
    # 50.0 BRL → 50_000_000 micros (1 BRL = 1M micros)
    assert (
        asset_op.field("asset_operation.create.promotion_asset.money_amount_off.amount_micros")
        == 50_000_000
    )
    assert (
        asset_op.field("asset_operation.create.promotion_asset.money_amount_off.currency_code")
        == "BRL"
    )


def test_builder_promotion_with_date_range_sets_both():
    from src.google_ads.mutates.assets import build_create_and_link_assets

    asset = {
        "type": "PROMOTION",
        "attachment_level": "CAMPAIGN",
        "attachment_id": "customers/1234567890/campaigns/99999",
        "promotion_target": "Verão 2026",
        "discount_modifier": "NONE",
        "percent_off": 20.0,
        "final_urls": ["https://example.com/promo"],
        "start_date": "2026-06-01",
        "end_date": "2026-06-30",
    }
    client = make_capture_client()
    ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets([asset]))

    asset_op = ops[0]
    assert asset_op.field("asset_operation.create.promotion_asset.start_date") == "2026-06-01"
    assert asset_op.field("asset_operation.create.promotion_asset.end_date") == "2026-06-30"


# ============================================================================
# Attachment level branching (3 tests)
# ============================================================================


def test_builder_customer_level_emits_customer_asset_op():
    from src.google_ads.mutates.assets import build_create_and_link_assets

    asset = _sitelink_minimal()
    asset["attachment_level"] = "CUSTOMER"
    asset["attachment_id"] = "1234567890"

    client = make_capture_client()
    ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets([asset]))

    link_op = ops[1]
    assert (
        link_op.field("customer_asset_operation.create.asset") == "customers/1234567890/assets/-1"
    )
    assert link_op.has("campaign_asset_operation") is False
    assert link_op.has("ad_group_asset_operation") is False


def test_builder_campaign_level_emits_campaign_asset_op_with_campaign_path():
    from src.google_ads.mutates.assets import build_create_and_link_assets

    asset = _sitelink_minimal()  # already CAMPAIGN level
    client = make_capture_client()
    ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets([asset]))

    link_op = ops[1]
    assert (
        link_op.field("campaign_asset_operation.create.asset") == "customers/1234567890/assets/-1"
    )
    assert (
        link_op.field("campaign_asset_operation.create.campaign")
        == "customers/1234567890/campaigns/99999"
    )


def test_builder_ad_group_level_emits_ad_group_asset_op_with_ad_group_path():
    from src.google_ads.mutates.assets import build_create_and_link_assets

    asset = _sitelink_minimal()
    asset["attachment_level"] = "AD_GROUP"
    asset["attachment_id"] = "customers/1234567890/adGroups/77777"

    client = make_capture_client()
    ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets([asset]))

    link_op = ops[1]
    assert (
        link_op.field("ad_group_asset_operation.create.asset") == "customers/1234567890/assets/-1"
    )
    assert (
        link_op.field("ad_group_asset_operation.create.ad_group")
        == "customers/1234567890/adGroups/77777"
    )


# ============================================================================
# Chained mutation invariants (4 tests)
# ============================================================================


def test_builder_emits_2n_ops_for_n_assets():
    from src.google_ads.mutates.assets import build_create_and_link_assets

    assets = [_sitelink_minimal() for _ in range(3)]
    client = make_capture_client()
    ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets(assets))

    assert len(ops) == 6  # 3 assets × 2 ops each


def test_builder_links_temp_resource_names_correctly():
    """Link op's asset field must match the matching CreateAssetOp's resource_name."""
    from src.google_ads.mutates.assets import build_create_and_link_assets

    assets = [_sitelink_minimal() for _ in range(2)]
    client = make_capture_client()
    ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets(assets))

    # Asset #1 → ops[0], Link #1 → ops[1]
    assert ops[0].field("asset_operation.create.resource_name") == "customers/1234567890/assets/-1"
    assert ops[1].field("campaign_asset_operation.create.asset") == "customers/1234567890/assets/-1"

    # Asset #2 → ops[2], Link #2 → ops[3]
    assert ops[2].field("asset_operation.create.resource_name") == "customers/1234567890/assets/-2"
    assert ops[3].field("campaign_asset_operation.create.asset") == "customers/1234567890/assets/-2"


def test_builder_field_type_set_on_link_op():
    """Each link op carries field_type matching the asset type."""
    from src.google_ads.mutates.assets import build_create_and_link_assets

    callout_asset = {
        "type": "CALLOUT",
        "attachment_level": "CAMPAIGN",
        "attachment_id": "customers/1234567890/campaigns/99999",
        "callout_text": "Atendimento 24h",
    }
    client = make_capture_client()
    ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets([callout_asset]))

    link_op = ops[1]
    # _BareEnumDict returns the key as-is — so field_type comes back as "CALLOUT"
    assert link_op.field("campaign_asset_operation.create.field_type") == "CALLOUT"


def test_builder_mixed_types_and_levels_in_single_call():
    """V4 onboarding workflow — mixed types and levels in one batch."""
    from src.google_ads.mutates.assets import build_create_and_link_assets

    sitelink_camp = _sitelink_minimal()  # CAMPAIGN
    callout_cust = {
        "type": "CALLOUT",
        "attachment_level": "CUSTOMER",
        "attachment_id": "1234567890",
        "callout_text": "Atendimento 24h",
    }
    call_camp = {
        "type": "CALL",
        "attachment_level": "CAMPAIGN",
        "attachment_id": "customers/1234567890/campaigns/99999",
        "phone_number": "(11) 98765-4321",
    }

    client = make_capture_client()
    ops = build_create_and_link_assets(
        client, "1234567890", _payload_with_assets([sitelink_camp, callout_cust, call_camp])
    )

    assert len(ops) == 6
    # Op 1 = SITELINK CAMPAIGN link — assert via scalar leaf (has() requires scalar, not sub-message)
    assert ops[1].field("campaign_asset_operation.create.asset") == "customers/1234567890/assets/-1"
    assert ops[1].has("customer_asset_operation.create.asset") is False
    # Op 3 = CALLOUT CUSTOMER link
    assert ops[3].field("customer_asset_operation.create.asset") == "customers/1234567890/assets/-2"
    assert ops[3].has("campaign_asset_operation.create.asset") is False
    # Op 5 = CALL CAMPAIGN link
    assert ops[5].field("campaign_asset_operation.create.asset") == "customers/1234567890/assets/-3"
    assert ops[5].has("customer_asset_operation.create.asset") is False


# ============================================================================
# V4 invariant explicit assertions (3 tests)
# ============================================================================


def test_builder_call_always_sets_country_code_br():
    """Regardless of phone format, country_code MUST be BR (V4 invariant)."""
    from src.google_ads.mutates.assets import build_create_and_link_assets

    for phone in ["1198765432", "(11) 98765-4321", "11 9 8765 4321"]:
        asset = {
            "type": "CALL",
            "attachment_level": "CAMPAIGN",
            "attachment_id": "customers/1234567890/campaigns/99999",
            "phone_number": phone,
        }
        client = make_capture_client()
        ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets([asset]))
        assert ops[0].field("asset_operation.create.call_asset.country_code") == "BR"


def test_builder_promotion_always_sets_language_code_pt_br():
    """V4 invariant: language_code hardcoded pt-BR regardless of payload.

    F39 Sprint 3b.25.1: was "pt" — Google rejects with "The language code is not
    supported." BCP 47 requires region-qualified for Google PROMOTION asset.
    """
    from src.google_ads.mutates.assets import build_create_and_link_assets

    asset = {
        "type": "PROMOTION",
        "attachment_level": "CAMPAIGN",
        "attachment_id": "customers/1234567890/campaigns/99999",
        "promotion_target": "Verão 2026",
        "discount_modifier": "NONE",
        "percent_off": 20.0,
        "final_urls": ["https://example.com/promo"],
    }
    client = make_capture_client()
    ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets([asset]))
    assert ops[0].field("asset_operation.create.promotion_asset.language_code") == "pt-BR"


def test_builder_promotion_money_amount_off_always_brl():
    """V4 invariant: BRL currency hardcoded."""
    from src.google_ads.mutates.assets import build_create_and_link_assets

    asset = {
        "type": "PROMOTION",
        "attachment_level": "CAMPAIGN",
        "attachment_id": "customers/1234567890/campaigns/99999",
        "promotion_target": "Verão 2026",
        "discount_modifier": "NONE",
        "money_amount_off_brl": 100.0,
        "final_urls": ["https://example.com/promo"],
    }
    client = make_capture_client()
    ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets([asset]))
    assert (
        ops[0].field("asset_operation.create.promotion_asset.money_amount_off.currency_code")
        == "BRL"
    )
