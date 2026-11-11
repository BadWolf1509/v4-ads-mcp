"""Caracterizacao dos lookups GAQL das 4 tools de mutate (Task I3).

Prende o texto exato da query, os kwargs entregues ao `run_report` (inclusive
`operation_name` e `audit_this_call`) e o formato das linhas devolvidas. O alvo do
patch e onde o nome e PROCURADO: a tool, antes da mudanca; `preflight`, depois.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current

_CUSTOMER = "1234567890"


@pytest.fixture
def ctx() -> Any:
    c = McpRequestContext(manager_id=uuid4(), session_id=uuid4())
    set_current(c)
    yield c
    clear_current()


def _kwargs_do_unico_call(fake: AsyncMock) -> dict[str, Any]:
    assert fake.await_count == 1
    args, kwargs = fake.await_args
    assert args == ()
    return dict(kwargs)


def _sem_formatter(kwargs: dict[str, Any]) -> tuple[dict[str, Any], Any]:
    resto = dict(kwargs)
    return resto, resto.pop("row_formatter")


@pytest.mark.asyncio
async def test_lance_de_grupo_query_kwargs_e_retorno(ctx: McpRequestContext) -> None:
    from src.mcp.tools.update_ad_group_bid import update_ad_group_bid

    fake = AsyncMock(return_value=[])
    with (
        patch(
            "src.mcp.tools.update_ad_group_bid.validate_manual_cpc_strategy",
            AsyncMock(return_value=None),
        ),
        patch(LOOKUP_GRUPO, fake),
    ):
        out = await update_ad_group_bid(
            {
                "customer_id": _CUSTOMER,
                "bids": [
                    {"ad_group_id": "11", "new_cpc_bid_brl": 1.0},
                    {"ad_group_id": "22", "new_cpc_bid_brl": 2.0},
                ],
            }
        )
    resto, fmt = _sem_formatter(_kwargs_do_unico_call(fake))
    assert resto == {
        "manager_id": ctx.manager_id,
        "session_id": ctx.session_id,
        "customer_id": _CUSTOMER,
        "query": (
            "SELECT ad_group.id, ad_group.name, ad_group.cpc_bid_micros\n"
            "        FROM ad_group\n"
            "        WHERE ad_group.id IN (11, 22)"
        ),
        "operation_name": "update_ad_group_bid_lookup",
    }
    linha = SimpleNamespace(ad_group=SimpleNamespace(id=11, name="G", cpc_bid_micros=1_500_000))
    assert fmt(linha) == {
        "ad_group_id": "11",
        "ad_group_name": "G",
        "current_cpc_bid_micros": 1_500_000,
    }
    # lookup vazio -> a tool recusa nomeando os ids ausentes
    assert out["status"] == "error"
    assert "['11', '22']" in out["error_message"]


@pytest.mark.asyncio
async def test_lance_de_keyword_query_kwargs_e_retorno(ctx: McpRequestContext) -> None:
    from src.mcp.tools.update_keyword_bid import update_keyword_bid

    fake = AsyncMock(return_value=[])
    with (
        patch(
            "src.mcp.tools.update_keyword_bid.validate_manual_cpc_strategy",
            AsyncMock(return_value=None),
        ),
        patch(LOOKUP_KEYWORD, fake),
    ):
        out = await update_keyword_bid(
            {
                "customer_id": _CUSTOMER,
                "bids": [
                    {"ad_group_id": "1", "criterion_id": "100", "new_cpc_bid_brl": 1.0},
                    {"ad_group_id": "2", "criterion_id": "200", "new_cpc_bid_brl": 2.0},
                ],
            }
        )
    resto, fmt = _sem_formatter(_kwargs_do_unico_call(fake))
    assert resto == {
        "manager_id": ctx.manager_id,
        "session_id": ctx.session_id,
        "customer_id": _CUSTOMER,
        "query": (
            "SELECT\n"
            "          ad_group.id,\n"
            "          ad_group_criterion.criterion_id,\n"
            "          ad_group_criterion.keyword.text,\n"
            "          ad_group_criterion.cpc_bid_micros\n"
            "        FROM keyword_view\n"
            "        WHERE ad_group_criterion.criterion_id IN (100, 200)"
        ),
        "operation_name": "update_keyword_bid_lookup",
    }
    linha = SimpleNamespace(
        ad_group=SimpleNamespace(id=1),
        ad_group_criterion=SimpleNamespace(
            criterion_id=100, keyword=SimpleNamespace(text="kw"), cpc_bid_micros=2_000_000
        ),
    )
    assert fmt(linha) == {
        "ad_group_id": "1",
        "criterion_id": "100",
        "keyword_text": "kw",
        "current_cpc_bid_micros": 2_000_000,
    }
    assert out["status"] == "error"
    assert "Keywords nao encontradas" in out["error_message"]


@pytest.mark.asyncio
async def test_orcamento_da_campanha_query_kwargs_e_retorno(ctx: McpRequestContext) -> None:
    from src.mcp.tools.update_campaign_budget import update_campaign_budget

    fake = AsyncMock(return_value=[])
    with patch(LOOKUP_ORCAMENTO, fake):
        out = await update_campaign_budget(
            {"customer_id": _CUSTOMER, "campaign_id": "555", "new_daily_budget_brl": 100.0}
        )
    resto, fmt = _sem_formatter(_kwargs_do_unico_call(fake))
    assert resto == {
        "manager_id": ctx.manager_id,
        "session_id": ctx.session_id,
        "customer_id": _CUSTOMER,
        "query": (
            "SELECT\n"
            "          campaign.id,\n"
            "          campaign.name,\n"
            "          campaign_budget.id,\n"
            "          campaign_budget.resource_name,\n"
            "          campaign_budget.explicitly_shared,\n"
            "          campaign_budget.amount_micros\n"
            "        FROM campaign\n"
            "        WHERE campaign.id = 555\n"
            "        LIMIT 1"
        ),
        "operation_name": "update_campaign_budget_lookup",
    }
    linha = SimpleNamespace(
        campaign=SimpleNamespace(name="C"),
        campaign_budget=SimpleNamespace(
            resource_name="customers/1/campaignBudgets/9",
            amount_micros=5_000_000,
            id=9,
            explicitly_shared=True,
        ),
    )
    assert fmt(linha) == {
        "campaign_budget_resource_name": "customers/1/campaignBudgets/9",
        "current_amount_micros": 5_000_000,
        "campaign_name": "C",
        "budget_id": "9",
        "explicitly_shared": True,
    }
    # lookup vazio -> a tool recusa nomeando a campanha
    assert out["status"] == "error"
    assert "555" in out["error_message"]


@pytest.mark.asyncio
async def test_interesses_query_kwargs_e_retorno(ctx: McpRequestContext) -> None:
    from src.mcp.tools.apply_audience import _validate_user_interest_taxonomies

    fake = AsyncMock(return_value=[{"id": "91501", "taxonomy_type": "VERTICAL_GEO"}])
    atts = [
        {
            "audience_type": "user_interest",
            "audience_resource_name": f"customers/1/userInterests/{i}",
        }
        for i in ("91501", "7")
    ]
    with patch(LOOKUP_INTERESSES, fake):
        erro = await _validate_user_interest_taxonomies(ctx, _CUSTOMER, atts)
    resto, fmt = _sem_formatter(_kwargs_do_unico_call(fake))
    assert resto == {
        "manager_id": ctx.manager_id,
        "session_id": ctx.session_id,
        "customer_id": _CUSTOMER,
        "query": (
            "SELECT user_interest.user_interest_id, user_interest.taxonomy_type "
            "FROM user_interest "
            "WHERE user_interest.user_interest_id IN (91501, 7)"
        ),
        "operation_name": "apply_audience_preflight_taxonomy_lookup",
        "audit_this_call": False,
    }
    linha = SimpleNamespace(
        user_interest=SimpleNamespace(
            user_interest_id=91501, taxonomy_type=SimpleNamespace(name="IN_MARKET")
        )
    )
    assert fmt(linha) == {"id": "91501", "taxonomy_type": "IN_MARKET"}
    assert erro is not None and "VERTICAL_GEO" in erro


# Alvos do patch: onde o nome e procurado (preflight, desde a Task I3).
LOOKUP_GRUPO = "src.google_ads.preflight.run_report"
LOOKUP_KEYWORD = "src.google_ads.preflight.run_report"
LOOKUP_ORCAMENTO = "src.google_ads.preflight.run_report"
LOOKUP_INTERESSES = "src.google_ads.preflight.run_report"


@pytest.mark.asyncio
async def test_funcoes_do_preflight_indexam_o_que_o_run_report_devolve() -> None:
    from src.google_ads import preflight

    mid, sid = uuid4(), uuid4()
    base = {"manager_id": mid, "session_id": sid, "customer_id": _CUSTOMER}
    grupo = {"ad_group_id": "1", "ad_group_name": "G", "current_cpc_bid_micros": 1}
    kw = {"ad_group_id": "1", "criterion_id": "9", "keyword_text": "k", "current_cpc_bid_micros": 1}
    orc = {"campaign_budget_resource_name": "rn", "current_amount_micros": 1}
    with patch(LOOKUP_GRUPO, AsyncMock(return_value=[grupo])):
        assert await preflight.buscar_lances_de_grupo(**base, ad_group_ids=["1"]) == {"1": grupo}
    with patch(LOOKUP_KEYWORD, AsyncMock(return_value=[kw])):
        assert await preflight.buscar_lances_de_keyword(**base, pares=[("1", "9")]) == {
            ("1", "9"): kw
        }
    with patch(LOOKUP_ORCAMENTO, AsyncMock(return_value=[orc])):
        assert await preflight.buscar_orcamento_da_campanha(**base, campaign_id="5") == orc
    with patch(LOOKUP_ORCAMENTO, AsyncMock(return_value=[])):
        assert await preflight.buscar_orcamento_da_campanha(**base, campaign_id="5") is None
    with patch(LOOKUP_INTERESSES, AsyncMock(return_value=[])):
        assert await preflight.buscar_interesses(**base, ids=["1"]) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("nome", ["grupo", "keyword", "interesses"])
async def test_id_nao_numerico_recusa_antes_do_run_report(nome: str) -> None:
    from src.google_ads import preflight

    base = {"manager_id": uuid4(), "session_id": uuid4(), "customer_id": _CUSTOMER}
    chamadas = {
        "grupo": preflight.buscar_lances_de_grupo(**base, ad_group_ids=["1 OR 1=1"]),
        "keyword": preflight.buscar_lances_de_keyword(**base, pares=[("1", "x")]),
        "interesses": preflight.buscar_interesses(**base, ids=["x"]),
    }
    fake = AsyncMock()
    with patch("src.google_ads.preflight.run_report", fake), pytest.raises(ValueError):
        await chamadas[nome]
    fake.assert_not_awaited()
    for outra, coro in chamadas.items():
        if outra != nome:
            coro.close()
