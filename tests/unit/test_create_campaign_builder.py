"""Unit tests for build_create_campaign (Sprint 3b.24)."""

from __future__ import annotations

from tests.unit.fixtures.proto_capture import make_capture_client


def _payload(**overrides):
    """Build a minimal valid payload."""
    base = {
        "name": "Test Campaign",
        "bidding_strategy": {"type": "MAXIMIZE_CONVERSIONS"},
        "daily_budget_brl": 10.0,
        "geo_targets": ["geoTargetConstants/2076"],  # Brazil
    }
    base.update(overrides)
    return base


def test_builder_happy_path_max_conversions_minimal():
    """MAX_CONVERSIONS + 1 geo → 4 ops total (budget + campaign + 1 geo + 1 language)."""
    from src.google_ads.mutates.campaigns import build_create_campaign

    client = make_capture_client()
    ops = build_create_campaign(client, "1234567890", _payload())

    assert len(ops) == 4  # 1 budget + 1 campaign + 1 geo + 1 language

    # Op 0: budget
    budget_op = ops[0]
    assert "campaignBudgets/-1" in budget_op.field("campaign_budget_operation.create.resource_name")
    assert budget_op.field("campaign_budget_operation.create.amount_micros") == 10_000_000
    assert budget_op.field("campaign_budget_operation.create.delivery_method") == "STANDARD"
    # Sprint 3b.24.2 F32: budget must be non-shared for standalone bidding strategies
    assert budget_op.field("campaign_budget_operation.create.explicitly_shared") is False

    # Op 1: campaign
    campaign_op = ops[1]
    assert "campaigns/-2" in campaign_op.field("campaign_operation.create.resource_name")
    assert campaign_op.field("campaign_operation.create.name") == "Test Campaign"
    assert campaign_op.field("campaign_operation.create.status") == "PAUSED"
    assert campaign_op.field("campaign_operation.create.advertising_channel_type") == "SEARCH"
    assert "campaignBudgets/-1" in campaign_op.field("campaign_operation.create.campaign_budget")
    # Network settings V4 defaults
    assert (
        campaign_op.field("campaign_operation.create.network_settings.target_google_search") is True
    )
    assert (
        campaign_op.field("campaign_operation.create.network_settings.target_search_network")
        is False
    )
    assert (
        campaign_op.field("campaign_operation.create.network_settings.target_content_network")
        is False
    )

    # Op 2: geo criterion
    geo_op = ops[2]
    assert "campaigns/-2" in geo_op.field("campaign_criterion_operation.create.campaign")
    assert (
        geo_op.field("campaign_criterion_operation.create.location.geo_target_constant")
        == "geoTargetConstants/2076"
    )

    # Op 3: language criterion (PT hardcoded)
    lang_op = ops[3]
    assert "campaigns/-2" in lang_op.field("campaign_criterion_operation.create.campaign")
    assert (
        lang_op.field("campaign_criterion_operation.create.language.language_constant")
        == "languageConstants/1014"
    )


def test_builder_target_cpa_sets_target_cpa_micros():
    from src.google_ads.mutates.campaigns import build_create_campaign

    client = make_capture_client()
    payload = _payload(bidding_strategy={"type": "TARGET_CPA", "target_cpa_brl": 25.0})
    ops = build_create_campaign(client, "1234567890", payload)

    campaign_op = ops[1]
    assert campaign_op.field("campaign_operation.create.target_cpa.target_cpa_micros") == 25_000_000


def test_builder_target_roas_sets_target_roas():
    from src.google_ads.mutates.campaigns import build_create_campaign

    client = make_capture_client()
    payload = _payload(bidding_strategy={"type": "TARGET_ROAS", "target_roas": 4.0})
    ops = build_create_campaign(client, "1234567890", payload)

    campaign_op = ops[1]
    assert campaign_op.field("campaign_operation.create.target_roas.target_roas") == 4.0


def test_builder_manual_cpc_with_enhanced_cpc_flag():
    from src.google_ads.mutates.campaigns import build_create_campaign

    client = make_capture_client()
    payload = _payload(bidding_strategy={"type": "MANUAL_CPC", "enhanced_cpc": True})
    ops = build_create_campaign(client, "1234567890", payload)

    campaign_op = ops[1]
    assert campaign_op.field("campaign_operation.create.manual_cpc.enhanced_cpc_enabled") is True


def test_builder_maximize_clicks_with_ceiling():
    from src.google_ads.mutates.campaigns import build_create_campaign

    client = make_capture_client()
    payload = _payload(
        bidding_strategy={
            "type": "MAXIMIZE_CLICKS",
            "cpc_bid_ceiling_brl": 2.5,
        }
    )
    ops = build_create_campaign(client, "1234567890", payload)

    campaign_op = ops[1]
    assert (
        campaign_op.field("campaign_operation.create.target_spend.cpc_bid_ceiling_micros")
        == 2_500_000
    )


def test_builder_multiple_geo_targets_emit_multiple_criterion_ops():
    from src.google_ads.mutates.campaigns import build_create_campaign

    client = make_capture_client()
    payload = _payload(
        geo_targets=[
            "geoTargetConstants/2076",  # Brazil
            "geoTargetConstants/20180",  # SP state
            "geoTargetConstants/1031590",  # São Paulo city
        ]
    )
    ops = build_create_campaign(client, "1234567890", payload)

    # 1 budget + 1 campaign + 3 geos + 1 language = 6 ops
    assert len(ops) == 6

    # Geo criterion ops at positions 2, 3, 4
    geo_paths = [
        ops[i].field("campaign_criterion_operation.create.location.geo_target_constant")
        for i in range(2, 5)
    ]
    assert geo_paths == [
        "geoTargetConstants/2076",
        "geoTargetConstants/20180",
        "geoTargetConstants/1031590",
    ]

    # Language op at position 5
    assert "languageConstants/1014" in ops[5].field(
        "campaign_criterion_operation.create.language.language_constant"
    )


def test_builder_schedule_dates_set_when_provided():
    from src.google_ads.mutates.campaigns import build_create_campaign

    client = make_capture_client()
    payload = _payload(start_date="2026-05-20", end_date="2026-12-31")
    ops = build_create_campaign(client, "1234567890", payload)

    campaign_op = ops[1]
    assert campaign_op.field("campaign_operation.create.start_date") == "2026-05-20"
    assert campaign_op.field("campaign_operation.create.end_date") == "2026-12-31"


def test_builder_omits_schedule_when_not_provided():
    from src.google_ads.mutates.campaigns import build_create_campaign

    client = make_capture_client()
    ops = build_create_campaign(client, "1234567890", _payload())

    campaign_op = ops[1]
    assert campaign_op.has("campaign_operation.create.start_date") is False
    assert campaign_op.has("campaign_operation.create.end_date") is False
