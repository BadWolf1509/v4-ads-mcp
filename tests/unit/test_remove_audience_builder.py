"""Unit tests for build_remove_audience builder using ProtoFieldCapture."""

from tests.unit.fixtures.proto_capture import make_capture_client


def test_builder_ad_group_single_criterion():
    """ad_group target → ad_group_criterion_operation.remove with ~-separated path."""
    from src.google_ads.mutates.audiences import build_remove_audience

    client = make_capture_client()
    payload = {
        "target_type": "ad_group",
        "target_id": "111",
        "criterion_ids": ["56976936578"],
    }
    ops = build_remove_audience(client, "1163862076", payload)
    assert len(ops) == 1
    assert (
        ops[0].field("ad_group_criterion_operation.remove")
        == "customers/1163862076/adGroupCriteria/111~56976936578"
    )


def test_builder_campaign_single_criterion():
    """campaign target → campaign_criterion_operation.remove with COMPOUND ~-separated path.

    Sprint 3b.6 A5 fix: CampaignCriterion uses compound key
    {campaign_id}~{criterion_id} (same as AdGroupCriterion), NOT flat as
    originally assumed. Real Google API resource_name format confirmed via
    SDK helper introspection + Mestre da Obra JP smoke (remove with flat
    path was silently accepted but did not actually remove).
    """
    from src.google_ads.mutates.audiences import build_remove_audience

    client = make_capture_client()
    payload = {
        "target_type": "campaign",
        "target_id": "22169885957",
        "criterion_ids": ["2480650242694"],
    }
    ops = build_remove_audience(client, "1163862076", payload)
    assert len(ops) == 1
    assert (
        ops[0].field("campaign_criterion_operation.remove")
        == "customers/1163862076/campaignCriteria/22169885957~2480650242694"
    )


def test_builder_emits_one_op_per_criterion_id():
    """3 criterion_ids → 3 ops (all in same target)."""
    from src.google_ads.mutates.audiences import build_remove_audience

    client = make_capture_client()
    payload = {
        "target_type": "ad_group",
        "target_id": "111",
        "criterion_ids": ["100", "200", "300"],
    }
    ops = build_remove_audience(client, "1163862076", payload)
    assert len(ops) == 3
    assert (
        ops[0].field("ad_group_criterion_operation.remove")
        == "customers/1163862076/adGroupCriteria/111~100"
    )
    assert (
        ops[1].field("ad_group_criterion_operation.remove")
        == "customers/1163862076/adGroupCriteria/111~200"
    )
    assert (
        ops[2].field("ad_group_criterion_operation.remove")
        == "customers/1163862076/adGroupCriteria/111~300"
    )


def test_builder_ad_group_path_includes_target_id_via_tilde():
    """Regression: ad_group resource_name has target_id~criterion_id (NOT just criterion_id)."""
    from src.google_ads.mutates.audiences import build_remove_audience

    client = make_capture_client()
    payload = {
        "target_type": "ad_group",
        "target_id": "999",
        "criterion_ids": ["1234"],
    }
    ops = build_remove_audience(client, "1163862076", payload)
    path = ops[0].field("ad_group_criterion_operation.remove")
    assert "999~1234" in path
    assert path.endswith("~1234")


def test_builder_campaign_path_includes_target_id_via_tilde():
    """Regression A5 (Sprint 3b.6 smoke): campaign resource_name uses compound
    {campaign_id}~{criterion_id} key — SAME format as ad_group.

    Prior version of this test asserted FLAT path (no ~) — that assumption was
    wrong, leading to a silent-acceptance bug in production (Google accepted the
    malformed flat path but did not actually remove the criterion). Confirmed
    via SDK CampaignCriterionServiceClient.campaign_criterion_path() helper
    which is the authoritative source.
    """
    from src.google_ads.mutates.audiences import build_remove_audience

    client = make_capture_client()
    payload = {
        "target_type": "campaign",
        "target_id": "999",
        "criterion_ids": ["1234"],
    }
    ops = build_remove_audience(client, "1163862076", payload)
    path = ops[0].field("campaign_criterion_operation.remove")
    assert path == "customers/1163862076/campaignCriteria/999~1234"
    assert "999~1234" in path  # Critical: compound key, not flat


def test_builder_empty_criterion_ids_returns_empty():
    """Defensive: empty list → empty ops (schema rejects this but builder is defensive)."""
    from src.google_ads.mutates.audiences import build_remove_audience

    client = make_capture_client()
    ops = build_remove_audience(
        client,
        "1163862076",
        {"target_type": "ad_group", "target_id": "111", "criterion_ids": []},
    )
    assert ops == []
