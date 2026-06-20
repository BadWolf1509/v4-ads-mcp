"""Builder test for ads.py build_update_ad_status (Onda 2 — fecha F50/F51)."""

from src.google_ads.mutates.ads import build_update_ad_status
from tests.unit.fixtures.proto_capture import make_capture_client


def test_update_ad_status_sets_status_and_mask() -> None:
    client = make_capture_client()
    client.enums.AdGroupAdStatusEnum = {
        "ENABLED": "ENABLED",
        "PAUSED": "PAUSED",
        "REMOVED": "REMOVED",
    }
    ops = build_update_ad_status(
        client,
        "1234567890",
        {"ads": [{"ad_group_id": "111", "ad_id": "222"}], "new_status": "PAUSED"},
    )
    assert len(ops) == 1
    base = "ad_group_ad_operation.update"
    assert ops[0].field(f"{base}.resource_name") == "customers/1234567890/adGroupAds/111~222"
    assert ops[0].field(f"{base}.status") == "PAUSED"
    assert list(client.copy_from.call_args_list[0].args[1].paths) == ["status"]
