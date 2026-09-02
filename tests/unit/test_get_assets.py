"""F134: a camada `customer_asset` era invisivel por tool curada.

O teste que importa e `test_consulta_as_TRES_camadas`: uma implementacao que
consultasse so `campaign_asset` passaria em todos os outros e reproduziria
exatamente o erro de 02/09 (checklist previa 4 vinculos, eram 6).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from src.mcp.tools._registry import get_tool
from src.mcp.tools.get_assets import get_assets


@pytest.fixture(autouse=True)
def _ctx():
    from src.mcp.context import McpRequestContext, clear_current, set_current

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _fake_run_report(por_recurso: dict[str, list[dict[str, Any]]]):
    queries: list[str] = []

    async def _run(**kwargs: Any) -> list[dict[str, Any]]:
        q = kwargs["query"]
        queries.append(q)
        for recurso, linhas in por_recurso.items():
            if f"FROM {recurso}" in q:
                return linhas
        return []

    return _run, queries


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


@pytest.mark.asyncio
async def test_consulta_as_TRES_camadas(monkeypatch) -> None:  # noqa: N802
    """O guard da falha que esta tool existe para impedir."""
    run, queries = _fake_run_report({})
    monkeypatch.setattr("src.mcp.tools.get_assets.run_report", run)
    await get_assets({"customer_id": "1234567890"})
    recursos = {
        r
        for r in ("customer_asset", "campaign_asset", "ad_group_asset")
        if any(f"FROM {r}" in q for q in queries)
    }
    assert recursos == {"customer_asset", "campaign_asset", "ad_group_asset"}


@pytest.mark.asyncio
async def test_vinculo_de_conta_aparece_na_saida(monkeypatch) -> None:
    run, _ = _fake_run_report(
        {"customer_asset": [_link(level="CUSTOMER", campaign_id=None, campaign_name=None)]}
    )
    monkeypatch.setattr("src.mcp.tools.get_assets.run_report", run)
    r = await get_assets({"customer_id": "1234567890"})
    assert [x["level"] for x in r["links"]] == ["CUSTOMER"]


@pytest.mark.asyncio
async def test_linha_removida_aparece_sem_filtro_explicito(monkeypatch) -> None:
    """Prova SO que a tool nao pos-filtra por status em Python.

    Fix round 2: este teste NAO prova que a query GAQL e' nao-filtrada — o
    fake de `run_report` (`_fake_run_report`) casa por `FROM <recurso>` e
    ignora o WHERE, entao devolveria a linha REMOVED mesmo que o builder
    filtrasse por status (reproduzido por sabotagem: injetar
    `WHERE campaign_asset.status = 'ENABLED'` no builder de campanha e este
    teste continua verde — ver relatorio da sessao). A prova de que o WHERE
    de verdade nunca filtra status vive em
    `test_assets_queries.py::test_nenhum_builder_filtra_por_status_no_where`,
    direto no texto da query. Este teste aqui prova a outra metade: que
    `get_assets`/`build_inventory` tambem nao descartam a linha REMOVED
    DEPOIS que ela chega.
    """
    run, _ = _fake_run_report(
        {"campaign_asset": [_link(status="REMOVED", primary_status="REMOVED")]}
    )
    monkeypatch.setattr("src.mcp.tools.get_assets.run_report", run)
    r = await get_assets({"customer_id": "1234567890"})
    assert r["links"][0]["status"] == "REMOVED"


@pytest.mark.asyncio
async def test_saida_traz_resource_name(monkeypatch) -> None:
    """Acoplamento com o remove_asset_link (classe F81): sem isto o gestor nao
    consegue encadear as duas tools sem cair no run_gaql."""
    run, _ = _fake_run_report({"campaign_asset": [_link()]})
    monkeypatch.setattr("src.mcp.tools.get_assets.run_report", run)
    r = await get_assets({"customer_id": "1234567890"})
    assert r["links"][0]["resource_name"].startswith("customers/")


def test_tool_registrada_como_defer_com_prefixo() -> None:
    t = get_tool("get_assets")
    assert t is not None
    assert t.bucket == "defer"
    assert t.description.startswith("[DEFER]")


def test_schema_tem_limit_com_teto() -> None:
    """Classe F98: ausencia de teto estoura o cap de token em conta grande."""
    t = get_tool("get_assets")
    assert t is not None
    limite = t.input_schema["properties"]["limit"]
    assert limite["default"] == 200
    assert limite["maximum"] == 1000


def _fake_run_report_respeitando_campaign_ids(por_recurso: dict[str, list[dict[str, Any]]]):
    """Como `_fake_run_report`, mas simula filtro server-side: se a query tiver
    `campaign.id IN (...)`, so devolve as linhas cujo campaign_id esta na
    clausula — igual o Google faria de verdade contra `campaign_ids`."""

    async def _run(**kwargs: Any) -> list[dict[str, Any]]:
        q = kwargs["query"]
        for recurso, linhas in por_recurso.items():
            if f"FROM {recurso}" not in q:
                continue
            if "campaign.id IN (" in q:
                ids = set(q.split("campaign.id IN (", 1)[1].split(")", 1)[0].split(","))
                return [ln for ln in linhas if ln.get("campaign_id") in ids]
            return linhas
        return []

    return _run


@pytest.mark.asyncio
async def test_campaign_ids_nao_calcula_orfao_falso(monkeypatch) -> None:  # noqa: N802
    """Reproducao do reviewer: `campaign_ids` restringe SO a camada
    `campaign_asset` — customer_asset e ad_group_asset continuam devolvendo a
    conta inteira. Asset 9 tem link REMOVED na campanha 111 e ENABLED na 222:
    sem filtro nao e orfao (tem vinculo vivo); com `campaign_ids=['111']` a
    camada de campanha some ENABLED da vista, e o veredito de orfao sobre esse
    recorte parcial estaria errado — por isso a chave nem aparece."""
    linhas = [
        _link(
            asset_id="9",
            campaign_id="111",
            campaign_name="A",
            status="REMOVED",
            primary_status="REMOVED",
            resource_name="customers/1/campaignAssets/111~9~CALLOUT",
        ),
        _link(
            asset_id="9",
            campaign_id="222",
            campaign_name="B",
            status="ENABLED",
            primary_status="ELIGIBLE",
            resource_name="customers/1/campaignAssets/222~9~CALLOUT",
        ),
    ]
    run = _fake_run_report_respeitando_campaign_ids({"campaign_asset": linhas})
    monkeypatch.setattr("src.mcp.tools.get_assets.run_report", run)

    sem_filtro = await get_assets({"customer_id": "1234567890"})
    assert sem_filtro["summary"]["assets_sem_vinculo_ativo"] == []
    assert sem_filtro["summary"]["orphan_scope"] == "conta_completa"

    com_filtro = await get_assets({"customer_id": "1234567890", "campaign_ids": ["111"]})
    assert "assets_sem_vinculo_ativo" not in com_filtro["summary"]
    assert com_filtro["summary"]["orphan_scope"] == "nao_calculado_com_filtro"


@pytest.mark.asyncio
async def test_field_type_tambem_suprime_a_lista_de_orfaos(monkeypatch) -> None:
    """A decisao cobre QUALQUER filtro ativo, nao so campaign_ids."""
    run, _ = _fake_run_report({})
    monkeypatch.setattr("src.mcp.tools.get_assets.run_report", run)
    r = await get_assets({"customer_id": "1234567890", "field_type": "CALLOUT"})
    assert "assets_sem_vinculo_ativo" not in r["summary"]
    assert r["summary"]["orphan_scope"] == "nao_calculado_com_filtro"


@pytest.mark.asyncio
async def test_exatamente_uma_das_tres_consultas_e_auditada(monkeypatch) -> None:
    """get_assets e o passo de descoberta antes de um remove_asset_link
    destrutivo — sem rastro nenhum em get_my_audit_log/detect_drift, isso
    ficava errado pro papel que a tool cumpre. As tres rodavam com
    audit_this_call=False sempre; agora exatamente UMA grava (nao as tres —
    uma chamada do gestor tem que virar uma linha, nao tres)."""
    chamadas: list[dict[str, Any]] = []

    async def _run(**kwargs: Any) -> list[dict[str, Any]]:
        chamadas.append(kwargs)
        return []

    monkeypatch.setattr("src.mcp.tools.get_assets.run_report", _run)
    await get_assets({"customer_id": "1234567890", "field_type": "CALLOUT"})

    assert len(chamadas) == 3
    auditadas = [c for c in chamadas if c["audit_this_call"]]
    assert len(auditadas) == 1, "get_assets deve gravar exatamente UMA linha de audit por chamada"
    assert auditadas[0]["params_summary"] == {
        "field_type": "CALLOUT",
        "campaign_ids": None,
        "limit": 200,
    }

    nao_auditadas = [c for c in chamadas if not c["audit_this_call"]]
    assert len(nao_auditadas) == 2
    assert all(c["params_summary"] is None for c in nao_auditadas), (
        "params_summary descartado (audit_this_call=False) nao deveria nem ser construido"
    )
