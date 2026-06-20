"""Builder tests for campaigns.py update_* mutates (Onda 2 — fecha F50/F51).

Estes builders shiparam sem teste de execução. Capture-client asserta os
campos proto, o FieldMask e (no bidding) o oneof correto + ausência dos outros.
"""

from src.google_ads.mutates.campaigns import (
    build_update_campaign_bidding,
    build_update_campaign_budget,
    build_update_campaign_status,
)
from tests.unit.fixtures.proto_capture import make_capture_client


def test_update_campaign_status_sets_status_and_mask() -> None:
    client = make_capture_client()
    ops = build_update_campaign_status(
        client, "1234567890", {"campaign_ids": ["111", "222"], "new_status": "PAUSED"}
    )
    assert len(ops) == 2
    base = "campaign_operation.update"
    assert ops[0].field(f"{base}.resource_name") == "customers/1234567890/campaigns/111"
    # CampaignStatusEnum é _BareEnumDict → subscript devolve a key
    assert ops[0].field(f"{base}.status") == "PAUSED"
    assert ops[1].field(f"{base}.resource_name") == "customers/1234567890/campaigns/222"
    assert list(client.copy_from.call_args_list[0].args[1].paths) == ["status"]
    # F51: não tocou outros campos
    assert ops[0].has(f"{base}.name") is False


def test_update_campaign_budget_sets_amount_and_mask() -> None:
    client = make_capture_client()
    ops = build_update_campaign_budget(
        client,
        "1234567890",
        {
            "campaign_budget_resource_name": "customers/1234567890/campaignBudgets/55",
            "new_amount_micros": 5_000_000,
        },
    )
    assert len(ops) == 1
    base = "campaign_budget_operation.update"
    assert ops[0].field(f"{base}.resource_name") == "customers/1234567890/campaignBudgets/55"
    assert ops[0].field(f"{base}.amount_micros") == 5_000_000
    assert list(client.copy_from.call_args_list[0].args[1].paths) == ["amount_micros"]


def test_bidding_target_cpa_sets_oneof_and_mask() -> None:
    client = make_capture_client()
    ops = build_update_campaign_bidding(
        client,
        "1234567890",
        {"campaign_id": "111", "strategy": "TARGET_CPA", "target_value_micros": 3_000_000},
    )
    base = "campaign_operation.update"
    assert ops[0].field(f"{base}.resource_name") == "customers/1234567890/campaigns/111"
    assert ops[0].field(f"{base}.target_cpa.target_cpa_micros") == 3_000_000
    assert list(client.copy_from.call_args_list[0].args[1].paths) == [
        "target_cpa.target_cpa_micros"
    ]
    # oneof guard: os outros branches NÃO foram setados
    assert ops[0].has(f"{base}.target_roas.target_roas") is False
    assert ops[0].has(f"{base}.maximize_conversions.target_cpa_micros") is False


def test_bidding_target_roas_sets_oneof_and_mask() -> None:
    client = make_capture_client()
    ops = build_update_campaign_bidding(
        client, "1234567890", {"campaign_id": "111", "strategy": "TARGET_ROAS", "target_roas": 4.0}
    )
    base = "campaign_operation.update"
    assert ops[0].field(f"{base}.target_roas.target_roas") == 4.0
    assert list(client.copy_from.call_args_list[0].args[1].paths) == ["target_roas.target_roas"]
    assert ops[0].has(f"{base}.target_cpa.target_cpa_micros") is False


def test_bidding_maximize_conversions_sets_oneof_and_mask() -> None:
    client = make_capture_client()
    ops = build_update_campaign_bidding(
        client,
        "1234567890",
        {
            "campaign_id": "111",
            "strategy": "MAXIMIZE_CONVERSIONS",
            "target_value_micros": 2_000_000,
        },
    )
    base = "campaign_operation.update"
    assert ops[0].field(f"{base}.maximize_conversions.target_cpa_micros") == 2_000_000
    assert list(client.copy_from.call_args_list[0].args[1].paths) == [
        "maximize_conversions.target_cpa_micros"
    ]
    assert ops[0].has(f"{base}.target_cpa.target_cpa_micros") is False


def test_bidding_unsupported_strategy_raises() -> None:
    client = make_capture_client()
    import pytest

    with pytest.raises(ValueError, match="Unsupported bidding strategy"):
        build_update_campaign_bidding(
            client, "1234567890", {"campaign_id": "111", "strategy": "FOO"}
        )
