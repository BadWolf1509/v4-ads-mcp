"""Integracao do trio Meta de performance: campaign, ad set e ad.

As tres tools compartilham o executor `_meta_performance`, entao o que e comum
(envelope, ordenacao por gasto, gate de conta, erro amigavel, periodo custom,
params enviados a Graph) roda parametrizado sobre a tool. O que e especifico de
uma tool (campos de pai do ad, `optimization_goal` do ad set, envelope e metricas
da campanha, F54/F89) vive em `extra` ou em `proibidos`/`fields_*` da `Spec`.

F89: os mocks NAO carregam metadata de entidade (`creative_id`, `billing_event`,
`daily_budget`, `effective_status`). A Meta Insights nunca a devolve (e metadata
de /ads, /adsets e /campaigns, F54): mock que a incluia descrevia uma resposta
impossivel e foi parte de por que o parser seguiu lendo campo morto por sprints.
Os casos `test_metadata_nao_pedida_nunca_vaza` mandam a metadata DE PROPOSITO e
exigem que o parser nao a repasse.
"""

import importlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.meta_ads.errors import MetaAdsFriendlyError
from tests.integration._seed import seed_manager, seed_meta_account

pytestmark = pytest.mark.asyncio

_GRAPH = "src.mcp.tools._meta_performance.run_meta_graph_get"


@dataclass(frozen=True)
class Spec:
    nome: str  # nome da tool == nome do modulo
    level: str  # `level` esperado na Graph
    id_field: str  # campo de id que tem de estar em `fields`
    nome_key: str  # chave do nome da entidade na linha devolvida
    body: dict[str, Any]  # 2+ linhas fora de ordem de gasto
    ordem: list[str]  # nomes esperados, por spend_brl DESC
    top_spend: float
    extra: Callable[[dict[str, Any]], None]  # asserts so desta tool no caminho feliz
    leak_row: dict[str, Any]  # linha com metadata NAO pedida
    leak_nome: str
    proibidos_na_linha: tuple[str, ...]  # chaves que nao podem sair na linha
    fields_presentes: tuple[str, ...] = ()
    fields_ausentes: tuple[str, ...] = ()
    kwargs_happy: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------- campaign


def _extra_campaign(result: dict[str, Any]) -> None:
    assert result["ad_account_id"] == "act_123456"
    assert result["ad_account_name"] == "Test Account"
    assert result["currency"] == "BRL"
    top = result["rows"][0]
    assert top["purchases"] == 20
    assert top["purchases_value_brl"] == 4000.0
    assert top["purchase_roas"] == 4.0
    # Spec 2026-09-26: evento nao reportado e null; a campanha de leads tem leads.
    assert top["leads"] is None
    assert result["rows"][1]["leads"] == 10
    assert result["rows"][1]["purchases"] is None
    assert result["atribuicao"] == "unificada"


_CAMPAIGN = Spec(
    nome="meta_get_campaign_performance",
    level="campaign",
    id_field="campaign_id",
    nome_key="campaign_name",
    body={
        "data": [
            {
                "campaign_id": "c1",
                "campaign_name": "Low spend",
                "objective": "OUTCOME_TRAFFIC",
                "spend": "100",
                "impressions": "1000",
                "clicks": "50",
                "ctr": "5.0",
                "cpc": "2.0",
                "actions": [{"action_type": "omni_purchase", "value": "1"}],
                "action_values": [{"action_type": "omni_purchase", "value": "50"}],
                "purchase_roas": [{"action_type": "omni_purchase", "value": "0.5"}],
            },
            {
                "campaign_id": "c2",
                "campaign_name": "High spend",
                "objective": "OUTCOME_SALES",
                "spend": "1000",
                "impressions": "10000",
                "clicks": "300",
                "ctr": "3.0",
                "cpc": "3.33",
                "actions": [{"action_type": "omni_purchase", "value": "20"}],
                "action_values": [{"action_type": "omni_purchase", "value": "4000"}],
                "purchase_roas": [{"action_type": "omni_purchase", "value": "4.0"}],
            },
            {
                "campaign_id": "c3",
                "campaign_name": "Mid spend",
                "objective": "OUTCOME_LEADS",
                "spend": "500",
                "impressions": "5000",
                "clicks": "100",
                "actions": [{"action_type": "lead", "value": "10"}],
            },
        ]
    },
    ordem=["High spend", "Mid spend", "Low spend"],
    top_spend=1000.0,
    extra=_extra_campaign,
    leak_row={
        "campaign_id": "c1",
        "campaign_name": "Camp",
        "effective_status": "ACTIVE",  # nao pedido: nao pode sair
        "spend": "0",
    },
    leak_nome="Camp",
    # F89: antes saia 'DESCONHECIDO' sempre.
    proibidos_na_linha=("effective_status", "effective_status_label"),
    # M.3.1 (F53): Meta Insights rejeita o filtro por effective_status.
    fields_ausentes=("effective_status",),
    kwargs_happy={"date_range": "LAST_7_DAYS"},
)

# ---------------------------------------------------------------- ad set


def _extra_adset(result: dict[str, Any]) -> None:
    assert result["rows"][0]["optimization_goal"] == "OFFSITE_CONVERSIONS"


_ADSET = Spec(
    nome="meta_get_ad_set_performance",
    level="adset",
    id_field="adset_id",
    nome_key="ad_set_name",
    body={
        "data": [
            {
                "adset_id": "as1",
                "adset_name": "AS Low",
                "campaign_id": "c1",
                "campaign_name": "Camp 1",
                "optimization_goal": "OFFSITE_CONVERSIONS",
                "spend": "200",
                "actions": [{"action_type": "purchase", "value": "2"}],
            },
            {
                "adset_id": "as2",
                "adset_name": "AS High",
                "campaign_id": "c1",
                "campaign_name": "Camp 1",
                "optimization_goal": "OFFSITE_CONVERSIONS",
                "spend": "1500",
                "actions": [{"action_type": "purchase", "value": "30"}],
            },
        ]
    },
    ordem=["AS High", "AS Low"],
    top_spend=1500.0,
    extra=_extra_adset,
    # F89 (era `test_cbo_adset_no_daily_budget_returns_none`): o antigo dizia cobrir o
    # caso CBO, mas a F54 tirou `daily_budget` da query e TODO ad set vinha None.
    leak_row={
        "adset_id": "as1",
        "adset_name": "CBO AS",
        "campaign_id": "c1",
        "campaign_name": "CBO Camp",
        "effective_status": "ACTIVE",  # nao pedido
        "daily_budget": "5000",  # idem
        "billing_event": "IMPRESSIONS",  # idem
        "spend": "100",
    },
    leak_nome="CBO AS",
    proibidos_na_linha=(
        "daily_budget_brl",
        "daily_budget",
        "billing_event",
        "effective_status",
    ),
    fields_presentes=("optimization_goal",),
)

# ---------------------------------------------------------------- ad


def _extra_ad(result: dict[str, Any]) -> None:
    top = result["rows"][0]
    assert top["ad_set_id"] == "as1"
    assert top["campaign_id"] == "c1"


_AD = Spec(
    nome="meta_get_ad_performance",
    level="ad",
    id_field="ad_id",
    nome_key="ad_name",
    body={
        "data": [
            {
                "ad_id": "ad1",
                "ad_name": "Ad Low",
                "adset_id": "as1",
                "adset_name": "AS 1",
                "campaign_id": "c1",
                "campaign_name": "Camp 1",
                "spend": "50",
                "impressions": "500",
                "clicks": "10",
            },
            {
                "ad_id": "ad2",
                "ad_name": "Ad High",
                "adset_id": "as1",
                "adset_name": "AS 1",
                "campaign_id": "c1",
                "campaign_name": "Camp 1",
                "spend": "500",
                "impressions": "5000",
                "clicks": "120",
                "actions": [{"action_type": "purchase", "value": "5"}],
            },
        ]
    },
    ordem=["Ad High", "Ad Low"],
    top_spend=500.0,
    extra=_extra_ad,
    # F89 (era `test_ad_missing_creative_id_returns_none`): a ausencia de `creative_id`
    # era UNIVERSAL, porque a query nunca pediu o campo.
    leak_row={
        "ad_id": "ad1",
        "ad_name": "Ad",
        "adset_id": "as1",
        "adset_name": "AS 1",
        "campaign_id": "c1",
        "campaign_name": "C",
        "effective_status": "PAUSED",  # nao pedido
        "creative_id": "cr9",  # idem
        "spend": "0",
    },
    leak_nome="Ad",
    proibidos_na_linha=("creative_id", "effective_status", "effective_status_label"),
    # M.3.1.1 (F54): `creative_id` saiu de INSIGHTS_FIELDS_AD; a Meta o rejeita.
    fields_ausentes=("creative_id",),
)

TOOLS = [
    pytest.param(_CAMPAIGN, id="campaign"),
    pytest.param(_ADSET, id="ad_set"),
    pytest.param(_AD, id="ad"),
]


def _tool(spec: Spec) -> Callable[..., Any]:
    return getattr(importlib.import_module(f"src.mcp.tools.{spec.nome}"), spec.nome)


async def _seed_com_acesso(db, *, account_status: int = 1) -> Any:
    async with db.acquire() as conn:
        mid = await seed_manager(conn)
        await seed_meta_account(conn, mid, account_status=account_status)
    return mid


async def _chamar(spec: Spec, db, *, graph: AsyncMock, **kwargs: Any) -> dict[str, Any]:
    mid = await _seed_com_acesso(db)
    with patch(_GRAPH, new=graph):
        return await _tool(spec)(
            manager_id=mid, session_id=uuid4(), ad_account_id="act_123456", **kwargs
        )


async def _capturar_params(spec: Spec, db, **kwargs: Any) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    async def capture_call(**kw: Any) -> dict[str, Any]:
        captured.update(kw["params"])
        return {"data": []}

    await _chamar(spec, db, graph=AsyncMock(side_effect=capture_call), **kwargs)
    return captured


@pytest.mark.integration
@pytest.mark.parametrize("spec", TOOLS)
async def test_happy_path_ordena_por_spend_desc(db, spec: Spec):
    """Linhas devolvidas em ordem de spend_brl DESC; asserts proprios via `extra`."""
    result = await _chamar(spec, db, graph=AsyncMock(return_value=spec.body), **spec.kwargs_happy)

    assert result["status"] == "success"
    assert result["total_rows"] == len(spec.ordem)
    assert [r[spec.nome_key] for r in result["rows"]] == spec.ordem
    assert result["rows"][0]["spend_brl"] == spec.top_spend
    # F89: metadata de entidade nao e devolvida.
    for chave in spec.proibidos_na_linha:
        assert chave not in result["rows"][0]
    spec.extra(result)


@pytest.mark.integration
@pytest.mark.parametrize("spec", TOOLS)
async def test_metadata_nao_pedida_nunca_vaza_pra_resposta(db, spec: Spec):
    """F89: mesmo que a Meta mande metadata sem ser pedida, o parser nao a repassa."""
    result = await _chamar(spec, db, graph=AsyncMock(return_value={"data": [spec.leak_row]}))

    assert result["status"] == "success"
    row = result["rows"][0]
    assert row[spec.nome_key] == spec.leak_nome
    for chave in spec.proibidos_na_linha:
        assert chave not in row


@pytest.mark.integration
@pytest.mark.parametrize("spec", TOOLS)
async def test_level_e_fields_enviados_a_graph(db, spec: Spec):
    """`level` correto, id nos fields; sem `filtering` (F53) e sem metadata (F54)."""
    params = await _capturar_params(spec, db)

    assert params["level"] == spec.level
    assert spec.id_field in params["fields"]
    for campo in spec.fields_presentes:
        assert campo in params["fields"]
    for campo in spec.fields_ausentes:
        assert campo not in params["fields"]
    # M.3.1 (F53): a Meta Insights rejeita o filtro por effective_status.
    assert "filtering" not in params
    assert "effective_status" not in params["fields"]


@pytest.mark.integration
@pytest.mark.parametrize("spec", TOOLS)
async def test_account_not_found_returns_error(db, spec: Spec):
    """ad_account_id fora do inventario -> erro PT-BR, sem chamar a Graph."""
    async with db.acquire() as conn:
        mid = await seed_manager(conn)

    graph = AsyncMock(return_value={"data": []})
    with patch(_GRAPH, new=graph):
        result = await _tool(spec)(manager_id=mid, session_id=uuid4(), ad_account_id="act_999999")

    assert result["status"] == "error"
    assert "act_999999" in result["error_message"]
    assert "não está no inventário" in result["error_message"]
    graph.assert_not_called()


@pytest.mark.integration
@pytest.mark.parametrize("spec", TOOLS)
async def test_meta_api_error_returns_friendly_pt_br(db, spec: Spec):
    """Erro da Graph -> mensagem PT-BR amigavel via to_friendly_meta_error."""
    erro = MetaAdsFriendlyError(
        "Limite Meta atingido. Tente novamente em alguns minutos.", retryable=True
    )
    result = await _chamar(spec, db, graph=AsyncMock(side_effect=erro))

    assert result["status"] == "error"
    assert "Limite Meta" in result["error_message"]


@pytest.mark.integration
@pytest.mark.parametrize("spec", TOOLS)
async def test_date_range_custom_overrides_preset(db, spec: Spec):
    """start_date+end_date sobrescreve o preset -> params.time_range custom."""
    params = await _capturar_params(
        spec,
        db,
        date_range="LAST_7_DAYS",  # deve ser sobrescrito
        start_date="2026-03-01",
        end_date="2026-03-31",
    )

    assert "2026-03-01" in params["time_range"]
    assert "2026-03-31" in params["time_range"]
