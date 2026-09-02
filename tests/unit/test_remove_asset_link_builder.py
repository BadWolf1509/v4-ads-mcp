"""Unlink de asset: remove o VINCULO, nunca a entidade Asset.

Asset orfao e inerte; remover a entidade e irreversivel e ela pode estar linkada
onde a varredura nao alcancou (spec secao 2).

Use `make_capture_client`, nunca MagicMock (F16/F42/F44): o MagicMock aceita
qualquer campo e esconde erro de nome de campo do proto.
"""

from __future__ import annotations

import pytest

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
    """A guarda da secao 2 da spec: so o vinculo sai, a entidade fica.

    Usa field() para resolver folhas concretas: has() retorna False pra qualquer
    oneof sub-message, mesmo tocado via .remove/.create/.update, impossibilitando
    distincao entre "nunca tocado" e "tocado via nested leaf". field() retorna None
    pra campos nao-tocados e o valor real pra tocados.
    """
    ops = build_remove_asset_link(
        make_capture_client(),
        "1234567890",
        _payload(("CAMPAIGN", "customers/1234567890/campaignAssets/7~9~CALLOUT")),
    )
    assert ops[0].field("asset_operation.remove") is None
    assert ops[0].field("asset_operation.create") is None
    assert ops[0].field("asset_operation.update") is None


def test_reject_unknown_level() -> None:
    """Nivel desconhecido levanta ValueError descritivo."""
    with pytest.raises(ValueError, match="unexpected attachment_level"):
        build_remove_asset_link(
            make_capture_client(),
            "1234567890",
            _payload(("INVALID_LEVEL", "customers/1234567890/campaignAssets/7~9")),
        )
