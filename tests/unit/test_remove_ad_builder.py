"""Builder do remove_ad (S3): uma `ad_group_ad_operation.remove` por anuncio.

Capture client (nao MagicMock, F16/F42/F44): o `remove` e um campo string do oneof;
`create`/`update` nao podem ser tocados — a operacao e remocao pura.
"""

from __future__ import annotations

from src.google_ads.mutates._common import get_builder, import_all_builders
from src.google_ads.mutates.ads import build_remove_ad
from tests.unit.fixtures.proto_capture import make_capture_client

_CID = "7862230676"


def test_builder_registrado() -> None:
    import_all_builders()
    assert get_builder("remove_ad") is build_remove_ad


def test_uma_operacao_remove_por_anuncio() -> None:
    client = make_capture_client()
    ops = build_remove_ad(
        client,
        _CID,
        {
            "ads": [
                {"ad_group_id": "100", "ad_id": "11"},
                {"ad_group_id": "200", "ad_id": "22"},
            ]
        },
    )
    assert len(ops) == 2
    assert ops[0].field("ad_group_ad_operation.remove") == f"customers/{_CID}/adGroupAds/100~11"
    assert ops[1].field("ad_group_ad_operation.remove") == f"customers/{_CID}/adGroupAds/200~22"
    for op in ops:
        assert op.has("ad_group_ad_operation.create.status") is False
        assert op.has("ad_group_ad_operation.update.status") is False
        assert op.has("ad_group_ad_operation.update.resource_name") is False
        assert op._raw("ad_group_ad_operation.create") is None
        assert op._raw("ad_group_ad_operation.update") is None
    client.copy_from.assert_not_called()


def test_mutate_operation_do_sdk_aceita_remove() -> None:
    """Probe do SDK instalado: `remove` e o campo string do oneof de AdGroupAdOperation."""
    from google.ads.googleads.v25.services.types.google_ads_service import MutateOperation

    op = MutateOperation()
    op.ad_group_ad_operation.remove = f"customers/{_CID}/adGroupAds/100~11"
    pb = MutateOperation.pb(op)
    assert pb.WhichOneof("operation") == "ad_group_ad_operation"
    assert pb.ad_group_ad_operation.WhichOneof("operation") == "remove"
