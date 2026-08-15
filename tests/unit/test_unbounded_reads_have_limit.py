"""F98: tres reads nao tinham teto NENHUM — nem no schema, nem no builder.

Nao e o caso "default alto demais" (classe F2/F22): `get_recommendations`,
`get_conversion_actions` e `get_budget_pacing` mandavam GAQL sem `LIMIT` e sem
expor `limit` no schema. As recomendacoes do Google escalam com o numero de
ad_groups (`RESPONSIVE_SEARCH_AD_ASSET` e `KEYWORD` sao por ad_group), entao
uma conta grande estoura o cap de token do MCP e a resposta inteira se perde.

As tres queries com `LIMIT 101` foram validadas contra a API real via
`validate_gaql` antes deste teste existir (licao F87 — nao assertar superficie
de API externa por analogia).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.google_ads.queries.overview import budget_pacing_query
from src.google_ads.queries.recommendations import recommendations_query
from src.google_ads.queries.tactical import conversion_actions_query
from src.mcp.context import McpRequestContext, clear_current, set_current
from src.mcp.tools.get_budget_pacing import _SCHEMA as SCHEMA_PACING
from src.mcp.tools.get_budget_pacing import get_budget_pacing
from src.mcp.tools.get_conversion_actions import _SCHEMA as SCHEMA_ACTIONS
from src.mcp.tools.get_conversion_actions import get_conversion_actions
from src.mcp.tools.get_recommendations import _SCHEMA as SCHEMA_RECS
from src.mcp.tools.get_recommendations import get_recommendations


@pytest.fixture(autouse=True)
def _ctx():
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


# --- Os builders passam a carregar teto -------------------------------------


@pytest.mark.parametrize(
    "builder",
    [recommendations_query, conversion_actions_query, budget_pacing_query],
    ids=["recommendations", "conversion_actions", "budget_pacing"],
)
def test_builder_emite_limit_com_a_linha_sentinela(builder: Any) -> None:
    """F98: `LIMIT limit+1` — a linha extra e o que detecta o corte.

    Mesmo truque de `bulk_pause.py` (`LIMIT 101` pra detectar >100): sem ela o
    tool nao consegue distinguir "vieram exatamente 100" de "tem mais".
    """
    assert "LIMIT 101" in builder(limit=100)
    assert "LIMIT 26" in builder(limit=25)


def test_budget_pacing_ordena_antes_de_cortar() -> None:
    """F98 + classe F88: cortar sem ordenar produz um "top" que nao e top.

    `_project` ordena por gasto DESC no fim. Se o `LIMIT` cortasse um conjunto
    nao-ordenado, o gestor receberia N campanhas arbitrarias reordenadas entre
    si — parecendo o topo de gasto da conta sem ser. Os outros dois tools sao
    inventario (nao ha ranking implicito), entao so este precisa do ORDER BY.
    """
    query = budget_pacing_query(limit=50)
    assert "ORDER BY metrics.cost_micros DESC" in query
    assert query.index("ORDER BY") < query.index("LIMIT")


# --- Os schemas passam a expor o teto ---------------------------------------


@pytest.mark.parametrize(
    "schema",
    [SCHEMA_RECS, SCHEMA_ACTIONS, SCHEMA_PACING],
    ids=["recommendations", "conversion_actions", "budget_pacing"],
)
def test_schema_expoe_limit_com_default_conservador(schema: dict[str, Any]) -> None:
    """F98: sem o param no schema o gestor nao tem como pedir mais nem menos."""
    limite = schema["properties"].get("limit")
    assert limite is not None, "schema sem `limit` — o teto fica invisivel pro cliente"
    assert limite["type"] == "integer"
    assert limite["default"] <= 100
    assert limite["maximum"] <= 1000
    assert limite["minimum"] == 1


# --- O corte precisa ser confessado -----------------------------------------


@pytest.mark.asyncio
async def test_recommendations_corta_no_teto_e_avisa() -> None:
    """F98: veio a linha sentinela → devolve `limit` linhas e `truncated: True`."""
    linhas = [{"resource_name": f"r{i}", "type": "KEYWORD", "type_pt": None} for i in range(4)]
    with patch("src.mcp.tools.get_recommendations.run_report", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = linhas
        out = await get_recommendations({"customer_id": "1234567890", "limit": 3})

    assert out["count"] == 3
    assert len(out["recommendations"]) == 3, "a linha sentinela vazou pro gestor"
    assert out["truncated"] is True


@pytest.mark.asyncio
async def test_recommendations_nao_mente_quando_coube() -> None:
    """F98: `truncated` so pode ser True quando realmente cortou."""
    linhas = [{"resource_name": f"r{i}", "type": "KEYWORD", "type_pt": None} for i in range(2)]
    with patch("src.mcp.tools.get_recommendations.run_report", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = linhas
        out = await get_recommendations({"customer_id": "1234567890", "limit": 3})

    assert out["count"] == 2
    assert out["truncated"] is False


@pytest.mark.asyncio
async def test_conversion_actions_corta_no_teto_e_avisa() -> None:
    linhas = [{"id": str(i), "name": f"acao {i}"} for i in range(4)]
    with patch(
        "src.mcp.tools.get_conversion_actions.run_report", new_callable=AsyncMock
    ) as mock_run:
        mock_run.return_value = linhas
        out = await get_conversion_actions({"customer_id": "1234567890", "limit": 3})

    assert out["count"] == 3
    assert len(out["actions"]) == 3
    assert out["truncated"] is True


@pytest.mark.asyncio
async def test_budget_pacing_corta_antes_de_projetar() -> None:
    """F98: a sentinela nao pode entrar na projecao — ela e uma campanha a mais."""
    linhas = [
        {
            "campaign_id": str(i),
            "campaign_name": f"Camp {i}",
            "daily_budget_brl": 100.0,
            "delivery_method": "STANDARD",
            "cost_micros_today": 1_000_000 * (10 - i),
        }
        for i in range(4)
    ]
    with patch("src.mcp.tools.get_budget_pacing.run_report", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = linhas
        out = await get_budget_pacing({"customer_id": "1234567890", "limit": 3})

    assert len(out["campaigns"]) == 3
    assert out["truncated"] is True


@pytest.mark.asyncio
async def test_limit_chega_ao_builder() -> None:
    """F98: o param tem que atravessar ate a query — senao o teto e decorativo."""
    with patch("src.mcp.tools.get_recommendations.run_report", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = []
        await get_recommendations({"customer_id": "1234567890", "limit": 7})

    assert "LIMIT 8" in mock_run.call_args.kwargs["query"]
