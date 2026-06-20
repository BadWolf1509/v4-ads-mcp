"""Builder tests for keywords.py update_keyword_* mutates (Onda 2 — fecha F50/F51).

resource_name é o path composto adGroupCriteria/{ag}~{crit}. update_keyword_bid
tem o mesmo clear-override (==0 omite cpc_bid_micros, mantém o mask).
"""

from src.google_ads.mutates.keywords import (
    build_update_keyword_bid,
    build_update_keyword_status,
)
from tests.unit.fixtures.proto_capture import make_capture_client


def test_update_keyword_status_sets_status_and_mask() -> None:
    client = make_capture_client()
    client.enums.AdGroupCriterionStatusEnum = {
        "ENABLED": "ENABLED",
        "PAUSED": "PAUSED",
        "REMOVED": "REMOVED",
    }
    ops = build_update_keyword_status(
        client,
        "1234567890",
        {"keywords": [{"ad_group_id": "111", "criterion_id": "222"}], "new_status": "PAUSED"},
    )
    assert len(ops) == 1
    base = "ad_group_criterion_operation.update"
    assert ops[0].field(f"{base}.resource_name") == "customers/1234567890/adGroupCriteria/111~222"
    assert ops[0].field(f"{base}.status") == "PAUSED"
    assert list(client.copy_from.call_args_list[0].args[1].paths) == ["status"]


def test_update_keyword_bid_sets_value_and_mask() -> None:
    client = make_capture_client()
    ops = build_update_keyword_bid(
        client,
        "1234567890",
        {"bids": [{"ad_group_id": "111", "criterion_id": "222", "new_cpc_bid_micros": 900_000}]},
    )
    base = "ad_group_criterion_operation.update"
    assert ops[0].field(f"{base}.resource_name") == "customers/1234567890/adGroupCriteria/111~222"
    assert ops[0].field(f"{base}.cpc_bid_micros") == 900_000
    assert list(client.copy_from.call_args_list[0].args[1].paths) == ["cpc_bid_micros"]


def test_update_keyword_bid_clear_override_omits_value_keeps_mask() -> None:
    client = make_capture_client()
    ops = build_update_keyword_bid(
        client,
        "1234567890",
        {"bids": [{"ad_group_id": "111", "criterion_id": "222", "new_cpc_bid_micros": 0}]},
    )
    base = "ad_group_criterion_operation.update"
    assert ops[0].has(f"{base}.cpc_bid_micros") is False
    assert list(client.copy_from.call_args_list[0].args[1].paths) == ["cpc_bid_micros"]
