"""Unlink de asset: remove o VINCULO, nunca a entidade Asset.

Asset orfao e inerte; remover a entidade e irreversivel e ela pode estar linkada
onde a varredura nao alcancou (spec secao 2).

Use `make_capture_client`, nunca MagicMock (F16/F42/F44): o MagicMock aceita
qualquer campo e esconde erro de nome de campo do proto.
"""

from __future__ import annotations

from src.google_ads.mutates.assets import build_remove_asset_link
from tests.unit.fixtures.proto_capture import make_capture_client


def _payload(*links: tuple[str, str]) -> dict:
    return {"links": [{"level": lv, "resource_name": rn} for lv, rn in links]}


def test_uma_operacao_por_vinculo() -> None:
    ops = build_remove_asset_link(
        make_capture_client(),
        "1234567890",
        _payload(
            ("CUSTOMER", "customers/1234567890/customerAssets/9~CALLOUT"),
            ("CAMPAIGN", "customers/1234567890/campaignAssets/7~9~CALLOUT"),
        ),
    )
    assert len(ops) == 2


def test_nivel_de_conta_usa_customer_asset_operation_remove() -> None:
    ops = build_remove_asset_link(
        make_capture_client(),
        "1234567890",
        _payload(("CUSTOMER", "customers/1234567890/customerAssets/9~CALLOUT")),
    )
    assert (
        ops[0].field("customer_asset_operation.remove")
        == "customers/1234567890/customerAssets/9~CALLOUT"
    )


def test_nivel_de_campanha_usa_campaign_asset_operation_remove() -> None:
    ops = build_remove_asset_link(
        make_capture_client(),
        "1234567890",
        _payload(("CAMPAIGN", "customers/1234567890/campaignAssets/7~9~CALLOUT")),
    )
    assert (
        ops[0].field("campaign_asset_operation.remove")
        == "customers/1234567890/campaignAssets/7~9~CALLOUT"
    )


def test_nivel_de_ad_group_usa_ad_group_asset_operation_remove() -> None:
    ops = build_remove_asset_link(
        make_capture_client(),
        "1234567890",
        _payload(("AD_GROUP", "customers/1234567890/adGroupAssets/5~9~CALLOUT")),
    )
    assert (
        ops[0].field("ad_group_asset_operation.remove")
        == "customers/1234567890/adGroupAssets/5~9~CALLOUT"
    )


def test_nunca_emite_operacao_sobre_a_entidade_asset() -> None:
    """A guarda da secao 2 da spec: so o vinculo sai, a entidade fica."""
    ops = build_remove_asset_link(
        make_capture_client(),
        "1234567890",
        _payload(("CAMPAIGN", "customers/1234567890/campaignAssets/7~9~CALLOUT")),
    )
    assert ops[0].has("asset_operation") is False
