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
    """Spec secao 7: `REMOVED` e a prova positiva; escondê-la mata a confirmacao."""
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
