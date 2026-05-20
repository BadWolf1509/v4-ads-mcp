"""Unit tests for build_update_conversion_action builder (Sprint 3b.27).

Uses ProtoFieldCapture (NOT MagicMock) per convention pós-Sprint 3b.5 —
silent attribute accept on MagicMock would mask field-name typos (F16/F42
lesson).

F44 (Sprint 3b.27.1): `include_in_conversions_metric` removed from V0 schema —
Google v24 marca field como immutable em ConversionAction.update (Silent-
acceptance family). Tests do field removidos. Pra desligar conv metric, use
Google Ads UI.
"""

from tests.unit.fixtures.proto_capture import make_capture_client


def test_build_op_sets_only_name_when_only_name_provided():
    from src.google_ads.mutates.conversion_actions import build_update_conversion_action

    client = make_capture_client()
    payload = {"updates": [{"conversion_action_id": "123", "name": "Novo Nome"}]}
    ops = build_update_conversion_action(client, "1163862076", payload)

    assert len(ops) == 1
    op = ops[0]
    assert op.field("conversion_action_operation.update.name") == "Novo Nome"
    assert op.has("conversion_action_operation.update.primary_for_goal") is False
    assert list(op.field("conversion_action_operation.update_mask.paths")) == ["name"]


def test_build_op_sets_primary_for_goal_field():
    from src.google_ads.mutates.conversion_actions import build_update_conversion_action

    client = make_capture_client()
    payload = {"updates": [{"conversion_action_id": "123", "primary_for_goal": False}]}
    ops = build_update_conversion_action(client, "1163862076", payload)

    op = ops[0]
    assert op.field("conversion_action_operation.update.primary_for_goal") is False
    assert list(op.field("conversion_action_operation.update_mask.paths")) == ["primary_for_goal"]


def test_build_op_constructs_correct_resource_name():
    from src.google_ads.mutates.conversion_actions import build_update_conversion_action

    client = make_capture_client()
    payload = {"updates": [{"conversion_action_id": "987654321", "name": "x"}]}
    ops = build_update_conversion_action(client, "1163862076", payload)

    op = ops[0]
    assert (
        op.field("conversion_action_operation.update.resource_name")
        == "customers/1163862076/conversionActions/987654321"
    )


def test_build_ops_handles_batch_with_different_field_combos():
    """F44: batch of 3 with distinct masks (name only / primary_for_goal only / both)."""
    from src.google_ads.mutates.conversion_actions import build_update_conversion_action

    client = make_capture_client()
    payload = {
        "updates": [
            {"conversion_action_id": "111", "name": "A"},
            {"conversion_action_id": "222", "primary_for_goal": False},
            {
                "conversion_action_id": "333",
                "name": "C",
                "primary_for_goal": True,
            },
        ]
    }
    ops = build_update_conversion_action(client, "1163862076", payload)

    assert len(ops) == 3
    assert list(ops[0].field("conversion_action_operation.update_mask.paths")) == ["name"]
    assert list(ops[1].field("conversion_action_operation.update_mask.paths")) == [
        "primary_for_goal"
    ]
    assert sorted(list(ops[2].field("conversion_action_operation.update_mask.paths"))) == sorted(
        ["name", "primary_for_goal"]
    )


def test_build_op_both_v0_fields_present():
    from src.google_ads.mutates.conversion_actions import build_update_conversion_action

    client = make_capture_client()
    payload = {
        "updates": [
            {
                "conversion_action_id": "555",
                "name": "Tudo",
                "primary_for_goal": True,
            }
        ]
    }
    ops = build_update_conversion_action(client, "1163862076", payload)

    op = ops[0]
    assert op.field("conversion_action_operation.update.name") == "Tudo"
    assert op.field("conversion_action_operation.update.primary_for_goal") is True
    assert sorted(list(op.field("conversion_action_operation.update_mask.paths"))) == sorted(
        ["name", "primary_for_goal"]
    )
