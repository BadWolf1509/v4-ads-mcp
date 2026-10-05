"""`run_gaql` com `compact: true` (spec 2026-10-05, §3.4).

A linha de entrada vem de `GoogleAdsRow` real pelo MESMO `MessageToDict` do `execute_gaql_raw`:
o `resource_name` implícito que se quer tirar só existe na mensagem real.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from google.protobuf.json_format import MessageToDict

from src.google_ads.gaql_compacto import campos_do_select, linha_compacta
from src.mcp.context import McpRequestContext, clear_current, set_current

_Q = (
    "SELECT campaign.id, campaign_criterion.criterion_id, campaign_criterion.keyword.text "
    "FROM campaign_criterion WHERE campaign_criterion.negative = TRUE"
)


def _linha_real() -> dict[str, Any]:
    from google.ads.googleads.v24.common.types.criteria import KeywordInfo
    from google.ads.googleads.v24.resources.types.campaign import Campaign
    from google.ads.googleads.v24.resources.types.campaign_criterion import CampaignCriterion
    from google.ads.googleads.v24.services.types.google_ads_service import GoogleAdsRow

    row = GoogleAdsRow(
        campaign=Campaign(resource_name="customers/1/campaigns/2", id=2),
        campaign_criterion=CampaignCriterion(
            resource_name="customers/1/campaignCriteria/2~3",
            criterion_id=3,
            keyword=KeywordInfo(text="brita"),
        ),
    )
    return MessageToDict(row._pb, preserving_proto_field_name=True)  # type: ignore[no-any-return]


def test_a_linha_real_traz_resource_name_que_o_select_nao_pediu() -> None:
    """Controle: sem isto o teste abaixo nao prova nada."""
    linha = _linha_real()
    assert linha["campaign"]["resource_name"] == "customers/1/campaigns/2"


def test_compacta_achata_e_tira_o_resource_name_implicito() -> None:
    assert linha_compacta(_linha_real(), campos_do_select(_Q)) == {
        "campaign.id": "2",
        "campaign_criterion.criterion_id": "3",
        "campaign_criterion.keyword.text": "brita",
    }


def test_resource_name_pedido_no_select_fica() -> None:
    q = _Q.replace("campaign.id,", "campaign.id, Campaign_Criterion.Resource_Name,")
    plana = linha_compacta(_linha_real(), campos_do_select(q))
    assert plana["campaign_criterion.resource_name"] == "customers/1/campaignCriteria/2~3"
    assert "campaign.resource_name" not in plana


def test_select_ilegivel_nao_tira_nada() -> None:
    assert campos_do_select("FROM campaign") is None
    plana = linha_compacta(_linha_real(), None)
    assert plana["campaign.resource_name"] == "customers/1/campaigns/2"
    assert plana["campaign_criterion.resource_name"] == "customers/1/campaignCriteria/2~3"


@pytest.fixture
def _ctx() -> Iterator[None]:
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


async def _rodar(**args: Any) -> dict[str, Any]:
    from src.mcp.tools.run_gaql import run_gaql

    linhas = [_linha_real(), _linha_real(), _linha_real()]
    with patch("src.mcp.tools.run_gaql.execute_gaql_raw", AsyncMock(return_value=linhas)):
        return await run_gaql({"customer_id": "7862230676", "query": _Q, **args})


@pytest.mark.usefixtures("_ctx")
async def test_a_tool_compacta_e_conta_as_linhas_de_antes_do_corte() -> None:
    out = await _rodar(compact=True, limit=2)
    assert out["row_count"] == 3 and out["returned"] == 2 and out["truncated"] is True
    assert out["rows"][0] == {
        "campaign.id": "2",
        "campaign_criterion.criterion_id": "3",
        "campaign_criterion.keyword.text": "brita",
    }


@pytest.mark.usefixtures("_ctx")
async def test_sem_compact_a_resposta_nao_muda() -> None:
    out = await _rodar()
    assert out["rows"][0] == _linha_real()


def test_description_e_schema() -> None:
    from src.mcp.tools._registry import get_tool, import_all_tools

    import_all_tools()
    t = get_tool("run_gaql")
    assert t is not None
    assert "compact: true" in t.description and "-39%" in t.description
    assert "o ganho depende da consulta" in t.description
    assert t.input_schema["properties"]["compact"]["default"] is False
