"""F134/F135: a camada `customer_asset` era invisivel. Estas queries sao a base
da leitura das TRES camadas.

`primary_status` e `primary_status_reasons` entram desde a v0: sao o veredito do
Google sobre servir, e substituem o `effective`/`shadowed_by` que a probe da
secao 5.1 da spec eliminou (o conceito nao existe na API).
"""

from __future__ import annotations

from types import SimpleNamespace

from src.google_ads.queries.assets import (
    build_ad_group_asset_query,
    build_campaign_asset_query,
    build_customer_asset_query,
    parse_ad_group_asset_row,
    parse_campaign_asset_row,
    parse_customer_asset_row,
)


def test_query_de_conta_pede_primary_status() -> None:
    q = build_customer_asset_query(field_type=None)
    assert "FROM customer_asset" in q
    assert "customer_asset.primary_status" in q
    assert "customer_asset.primary_status_reasons" in q


def test_query_de_conta_nao_filtra_status() -> None:
    """Spec section 7: filtrar por status esconde o REMOVED, que e a prova positiva."""
    q = build_customer_asset_query(field_type=None)
    assert "status = 'ENABLED'" not in q
    assert "status='ENABLED'" not in q


def test_filtro_de_field_type_e_opcional_e_escapado() -> None:
    sem = build_customer_asset_query(field_type=None)
    com = build_customer_asset_query(field_type="CALLOUT")
    assert "field_type" not in sem.split("FROM")[1]
    assert "customer_asset.field_type = 'CALLOUT'" in com


def test_query_de_campanha_filtra_por_campaign_ids() -> None:
    q = build_campaign_asset_query(field_type=None, campaign_ids=["111", "222"])
    assert "campaign.id IN (111,222)" in q


def test_query_de_ad_group_existe_e_aponta_o_recurso_certo() -> None:
    """A terceira camada e a que ninguem lembra — por isso tem teste proprio."""
    q = build_ad_group_asset_query(field_type=None)
    assert "FROM ad_group_asset" in q
    assert "ad_group_asset.primary_status" in q


def test_parser_de_conta_marca_o_level_e_nao_inventa_campanha() -> None:
    row = SimpleNamespace(
        customer_asset=SimpleNamespace(
            resource_name="customers/1/customerAssets/9~CALLOUT",
            field_type=SimpleNamespace(name="CALLOUT"),
            status=SimpleNamespace(name="ENABLED"),
            primary_status=SimpleNamespace(name="ELIGIBLE"),
            primary_status_reasons=[],
        ),
        asset=SimpleNamespace(id=9, name="Atendimento Eficaz"),
    )
    d = parse_customer_asset_row(row)
    assert d["level"] == "CUSTOMER"
    assert d["asset_id"] == "9"
    assert d["primary_status"] == "ELIGIBLE"
    assert d["campaign_id"] is None
    assert d["ad_group_id"] is None
    assert d["resource_name"] == "customers/1/customerAssets/9~CALLOUT"


def test_parser_traduz_enum_de_reason_para_nome() -> None:
    """Licao UX-2: `.name` do enum, nunca str(enum) — proto-plus tem repr feio."""
    row = SimpleNamespace(
        customer_asset=SimpleNamespace(
            resource_name="customers/1/customerAssets/9~CALLOUT",
            field_type=SimpleNamespace(name="CALLOUT"),
            status=SimpleNamespace(name="REMOVED"),
            primary_status=SimpleNamespace(name="REMOVED"),
            primary_status_reasons=[SimpleNamespace(name="ASSET_LINK_REMOVED")],
        ),
        asset=SimpleNamespace(id=9, name=""),
    )
    assert parse_customer_asset_row(row)["primary_status_reasons"] == ["ASSET_LINK_REMOVED"]


def test_parser_de_campanha_preenche_campanha() -> None:
    row = SimpleNamespace(
        campaign_asset=SimpleNamespace(
            resource_name="customers/1/campaignAssets/7~9~CALLOUT",
            field_type=SimpleNamespace(name="CALLOUT"),
            status=SimpleNamespace(name="ENABLED"),
            primary_status=SimpleNamespace(name="ELIGIBLE"),
            primary_status_reasons=[],
        ),
        asset=SimpleNamespace(id=9, name="X"),
        campaign=SimpleNamespace(id=7, name="JPA"),
    )
    d = parse_campaign_asset_row(row)
    assert d["level"] == "CAMPAIGN"
    assert d["campaign_id"] == "7"
    assert d["campaign_name"] == "JPA"
    assert d["ad_group_id"] is None


def test_parser_de_ad_group_preenche_ad_group_e_campanha() -> None:
    """A terceira camada e a que ninguem lembra — por isso tem teste proprio."""
    row = SimpleNamespace(
        ad_group_asset=SimpleNamespace(
            resource_name="customers/1/adGroupAssets/5~9~CALLOUT",
            field_type=SimpleNamespace(name="CALLOUT"),
            status=SimpleNamespace(name="ENABLED"),
            primary_status=SimpleNamespace(name="ELIGIBLE"),
            primary_status_reasons=[],
        ),
        asset=SimpleNamespace(id=9, name="X"),
        campaign=SimpleNamespace(id=7, name="JPA"),
        ad_group=SimpleNamespace(id=5, name="AG-1"),
    )
    d = parse_ad_group_asset_row(row)
    assert d["level"] == "AD_GROUP"
    assert d["campaign_id"] == "7"
    assert d["campaign_name"] == "JPA"
    assert d["ad_group_id"] == "5"
    assert d["ad_group_name"] == "AG-1"
