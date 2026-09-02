"""Agregacao pura do inventario de assets. Sem SDK, sem I/O."""

from __future__ import annotations

from typing import Any

from src.google_ads.asset_inventory import build_inventory


def _link(**kw: Any) -> dict[str, Any]:
    base = {
        "level": "CAMPAIGN",
        "resource_name": "customers/1/campaignAssets/7~9~CALLOUT",
        "asset_id": "9",
        "asset_name": "X",
        "field_type": "CALLOUT",
        "status": "ENABLED",
        "primary_status": "ELIGIBLE",
        "primary_status_reasons": [],
        "campaign_id": "7",
        "campaign_name": "JPA",
        "ad_group_id": None,
        "ad_group_name": None,
    }
    base.update(kw)
    return base


def test_ordena_por_asset_e_depois_por_camada() -> None:
    """Agrupar visualmente por asset e o que faz a camada dormente saltar."""
    rows = [
        _link(asset_id="2", level="CAMPAIGN"),
        _link(asset_id="1", level="CAMPAIGN"),
        _link(asset_id="1", level="CUSTOMER", campaign_id=None),
    ]
    links, _ = build_inventory(rows=rows, limit=100, filter_active=False)
    assert [(x["asset_id"], x["level"]) for x in links] == [
        ("1", "CUSTOMER"),
        ("1", "CAMPAIGN"),
        ("2", "CAMPAIGN"),
    ]


def test_summary_conta_por_camada() -> None:
    rows = [
        _link(asset_id="1", level="CUSTOMER", campaign_id=None),
        _link(asset_id="1", level="CAMPAIGN"),
        _link(asset_id="1", level="AD_GROUP", ad_group_id="5"),
    ]
    _, summary = build_inventory(rows=rows, limit=100, filter_active=False)
    assert summary["by_level"] == {"CUSTOMER": 1, "CAMPAIGN": 1, "AD_GROUP": 1}
    assert summary["total_links"] == 3


def test_summary_conta_por_primary_status() -> None:
    rows = [
        _link(asset_id="1", primary_status="ELIGIBLE"),
        _link(asset_id="2", primary_status="REMOVED"),
        _link(asset_id="3", primary_status="REMOVED"),
    ]
    _, summary = build_inventory(rows=rows, limit=100, filter_active=False)
    assert summary["by_primary_status"] == {"ELIGIBLE": 1, "REMOVED": 2}


def test_asset_so_com_vinculo_removido_conta_como_orfao() -> None:
    """Inventario do lixo sem precisar de tool destrutiva."""
    rows = [
        _link(asset_id="1", status="REMOVED", primary_status="REMOVED"),
        _link(asset_id="2", status="ENABLED", primary_status="ELIGIBLE"),
    ]
    _, summary = build_inventory(rows=rows, limit=100, filter_active=False)
    assert summary["assets_sem_vinculo_ativo"] == ["1"]


def test_asset_com_um_vinculo_vivo_em_qualquer_camada_nao_e_orfao() -> None:
    """O vinculo vivo pode estar na camada que ninguem olhou — era o bug de 02/09."""
    rows = [
        _link(asset_id="1", level="CAMPAIGN", status="REMOVED", primary_status="REMOVED"),
        _link(
            asset_id="1",
            level="CUSTOMER",
            campaign_id=None,
            status="ENABLED",
            primary_status="ELIGIBLE",
        ),
    ]
    _, summary = build_inventory(rows=rows, limit=100, filter_active=False)
    assert summary["assets_sem_vinculo_ativo"] == []


def test_limit_trunca_e_sinaliza() -> None:
    rows = [_link(asset_id=str(i)) for i in range(5)]
    links, summary = build_inventory(rows=rows, limit=2, filter_active=False)
    assert len(links) == 2
    assert summary["truncated"] is True
    assert summary["total_links"] == 5, "o summary conta o total bruto, nao o truncado"


def test_filtro_ativo_omite_lista_de_orfaos_e_diz_o_motivo() -> None:
    """Classe do proprio branch (F134, ao contrario): com field_type OU
    campaign_ids ativos, `build_inventory` so enxerga um recorte — um asset
    com o unico vinculo ENABLED fora do recorte viraria 'orfao' por engano.
    Um campo AUSENTE nao pode produzir veredito falso; um campo
    presente-porem-errado pode. Por isso a chave some, em vez de sair errada."""
    rows = [_link(asset_id="1", status="REMOVED", primary_status="REMOVED")]
    _, summary = build_inventory(rows=rows, limit=100, filter_active=True)
    assert "assets_sem_vinculo_ativo" not in summary
    assert summary["orphan_scope"] == "nao_calculado_com_filtro"


def test_sem_filtro_lista_de_orfaos_vem_com_escopo_conta_completa() -> None:
    rows = [_link(asset_id="1", status="REMOVED", primary_status="REMOVED")]
    _, summary = build_inventory(rows=rows, limit=100, filter_active=False)
    assert summary["assets_sem_vinculo_ativo"] == ["1"]
    assert summary["orphan_scope"] == "conta_completa"
