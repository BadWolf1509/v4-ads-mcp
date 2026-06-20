"""Builder tests for ad_groups.py update_* mutates (Onda 2 — fecha F50/F51).

O ponto sutil: update_ad_group_bid com new_cpc_bid_micros==0 NÃO seta o campo
(clear override) mas mantém o FieldMask — testar a AUSÊNCIA é o que pega a regressão.
"""

from src.google_ads.mutates.ad_groups import (
    build_update_ad_group_bid,
    build_update_ad_group_status,
)
from tests.unit.fixtures.proto_capture import make_capture_client

_STATUS_ENUM = {"ENABLED": "ENABLED", "PAUSED": "PAUSED", "REMOVED": "REMOVED"}


def test_update_ad_group_status_sets_status_and_mask() -> None:
    client = make_capture_client()
    client.enums.AdGroupStatusEnum = _STATUS_ENUM  # subscript → key (fixture é MagicMock)
    ops = build_update_ad_group_status(
        client, "1234567890", {"ad_group_ids": ["111"], "new_status": "PAUSED"}
    )
    assert len(ops) == 1
    base = "ad_group_operation.update"
    assert ops[0].field(f"{base}.resource_name") == "customers/1234567890/adGroups/111"
    assert ops[0].field(f"{base}.status") == "PAUSED"
    assert list(client.copy_from.call_args_list[0].args[1].paths) == ["status"]


def test_update_ad_group_bid_sets_value_and_mask() -> None:
    client = make_capture_client()
    ops = build_update_ad_group_bid(
        client, "1234567890", {"bids": [{"ad_group_id": "111", "new_cpc_bid_micros": 1_500_000}]}
    )
    base = "ad_group_operation.update"
    assert ops[0].field(f"{base}.resource_name") == "customers/1234567890/adGroups/111"
    assert ops[0].field(f"{base}.cpc_bid_micros") == 1_500_000
    assert list(client.copy_from.call_args_list[0].args[1].paths) == ["cpc_bid_micros"]


def test_update_ad_group_bid_clear_override_omits_value_keeps_mask() -> None:
    client = make_capture_client()
    ops = build_update_ad_group_bid(
        client, "1234567890", {"bids": [{"ad_group_id": "111", "new_cpc_bid_micros": 0}]}
    )
    base = "ad_group_operation.update"
    # CRÍTICO: cpc_bid_micros NÃO setado (clear), mas o mask sinaliza o clear
    assert ops[0].has(f"{base}.cpc_bid_micros") is False
    assert list(client.copy_from.call_args_list[0].args[1].paths) == ["cpc_bid_micros"]
