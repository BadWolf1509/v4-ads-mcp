"""Orcamento compartilhado no `get_budget_pacing`: o ritmo e do orcamento, nao da campanha.

Cada campanha era comparada com o orcamento inteiro. Medido em 29/09 na Mestre da Obra -
Joao Pessoa: as duas campanhas ativas dividem o orcamento 15803241252 (R$ 310/dia,
`explicitly_shared`), e a tool dizia 85% (JPA) e 9% (CAB) de R$ 9.300 cada — somar as
linhas dava R$ 18.600 de orcamento, o dobro. O certo: R$ 8.795,07 de R$ 9.300 (94,6%).

O total do orcamento vem do proprio `campaign_budget` (a GAQL aceita `metrics.cost_micros`
ali), nao da soma das linhas listadas: campanha pausada no meio do mes, ou cortada pelo
`limit`, gastou do mesmo orcamento e nao aparece na lista.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from freezegun import freeze_time

from src.mcp.context import McpRequestContext, clear_current, set_current

_CONTA = "7862230676"
_ORC = "15803241252"


@pytest.fixture(autouse=True)
def _ctx() -> Iterator[None]:
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _linha(
    cid: str, custo_brl: float, *, orc: str, compartilhado: bool, diario: float = 310.0
) -> dict[str, Any]:
    return {
        "campaign_id": cid,
        "campaign_name": f"Camp {cid}",
        "daily_budget_brl": diario,
        "delivery_method": "STANDARD",
        "budget_id": orc,
        "budget_name": f"Orcamento {orc}",
        "orcamento_compartilhado": compartilhado,
        "cost_micros": round(custo_brl * 1_000_000),
    }


def _gasto(chave: str, valor: str, custo_brl: float) -> dict[str, Any]:
    return {chave: valor, "cost_micros": round(custo_brl * 1_000_000)}


async def _pacing(respostas: list[list[dict[str, Any]]]) -> tuple[Any, AsyncMock]:
    from src.mcp.tools.get_budget_pacing import get_budget_pacing

    with patch("src.mcp.tools.get_budget_pacing.run_report", new_callable=AsyncMock) as rr:
        rr.side_effect = respostas
        out = await get_budget_pacing({"customer_id": _CONTA})
    return out, rr


def _mo_jp() -> list[list[dict[str, Any]]]:
    """A conta medida, com uma campanha PAUSADA que gastou R$ 204,93 do mesmo orcamento."""
    return [
        [
            _linha("21359547724", 7946.18, orc=_ORC, compartilhado=True),
            _linha("22169885957", 848.89, orc=_ORC, compartilhado=True),
            _linha("555", 100.0, orc="777", compartilhado=False, diario=10.0),
        ],
        [_gasto("campaign_id", "21359547724", 250.0)],  # hoje, por campanha
        [_gasto("budget_id", _ORC, 9000.0)],  # dias fechados, pelo orcamento
        [_gasto("budget_id", _ORC, 262.0)],  # hoje, pelo orcamento
    ]


@pytest.mark.asyncio
@freeze_time("2026-09-29 15:00:00")
async def test_campanha_de_orcamento_compartilhado_nao_tem_percentual_proprio() -> None:
    out, _ = await _pacing(_mo_jp())
    por_id = {c["campaign_id"]: c for c in out["campaigns"]}
    for cid in ("21359547724", "22169885957"):
        c = por_id[cid]
        assert c["orcamento_compartilhado"] is True
        assert c["budget_id"] == _ORC
        assert c["spent_pct_of_monthly_budget"] is None
        assert c["projection_vs_budget_pct"] is None
        # o resto da linha segue: gasto e projecao sao da campanha
        assert c["projected_monthly_brl"] is not None
    sozinha = por_id["555"]
    assert sozinha["orcamento_compartilhado"] is False
    assert sozinha["budget_id"] == "777"
    assert sozinha["spent_pct_of_monthly_budget"] == round(100.0 / 300.0 * 100, 1)


@pytest.mark.asyncio
@freeze_time("2026-09-29 15:00:00")
async def test_total_do_orcamento_vem_do_campaign_budget_nao_da_soma_das_linhas() -> None:
    out, _ = await _pacing(_mo_jp())
    (orc,) = out["orcamentos_compartilhados"]
    assert orc["budget_id"] == _ORC
    assert orc["daily_budget_brl"] == 310.0
    assert orc["monthly_budget_brl"] == 9300.0
    assert orc["campaign_ids"] == ["21359547724", "22169885957"]
    # 9.000 do orcamento, nao 8.795,07 das duas linhas listadas
    assert orc["spent_mtd_brl"] == 9000.0
    assert orc["gasto_hoje_brl"] == 262.0
    assert orc["projected_monthly_brl"] == round(9000.0 / 28 * 30, 2)
    assert orc["spent_pct_of_monthly_budget"] == round(9000.0 / 9300.0 * 100, 1)
    assert orc["projection_vs_budget_pct"] == round(9000.0 / 28 * 30 / 9300.0 * 100, 1)


@pytest.mark.asyncio
@freeze_time("2026-09-29 15:00:00")
async def test_queries_do_orcamento_pelos_dias_fechados_e_por_hoje() -> None:
    _, rr = await _pacing(_mo_jp())
    assert rr.await_count == 4
    fechados = rr.await_args_list[2].kwargs["query"]
    hoje = rr.await_args_list[3].kwargs["query"]
    for q in (fechados, hoje):
        assert "FROM campaign_budget" in q
        assert f"campaign_budget.id IN ({_ORC})" in q
    assert "segments.date BETWEEN '2026-09-01' AND '2026-09-28'" in fechados
    assert "segments.date BETWEEN '2026-09-29' AND '2026-09-29'" in hoje


@pytest.mark.asyncio
@freeze_time("2026-09-29 15:00:00")
async def test_sem_orcamento_compartilhado_nao_ha_query_nem_bloco() -> None:
    out, rr = await _pacing(
        [
            [_linha("555", 100.0, orc="777", compartilhado=False)],
            [_gasto("campaign_id", "555", 1.0)],
        ]
    )
    assert rr.await_count == 2
    assert out["orcamentos_compartilhados"] == []


@pytest.mark.asyncio
@freeze_time("2026-10-01 11:00:00")
async def test_dia_um_uma_query_de_orcamento_e_sem_projecao() -> None:
    out, rr = await _pacing(
        [
            [_linha("1", 20.0, orc=_ORC, compartilhado=True)],
            [_gasto("budget_id", _ORC, 25.0)],
        ]
    )
    assert rr.await_count == 2
    assert "BETWEEN '2026-10-01' AND '2026-10-01'" in rr.await_args_list[1].kwargs["query"]
    (orc,) = out["orcamentos_compartilhados"]
    assert orc["spent_mtd_brl"] == 25.0
    assert orc["gasto_hoje_brl"] == 25.0  # no dia 1 a janela E hoje
    assert orc["projected_monthly_brl"] is None
    assert orc["projection_vs_budget_pct"] is None


@pytest.mark.asyncio
@freeze_time("2026-09-29 15:00:00")
async def test_orcamento_sem_linha_na_query_e_gasto_zero_medido() -> None:
    """A query rodou e nao trouxe o orcamento: zero medido, como o gasto de hoje (F199)."""
    respostas = _mo_jp()
    respostas[3] = []
    out, _ = await _pacing(respostas)
    (orc,) = out["orcamentos_compartilhados"]
    assert orc["gasto_hoje_brl"] == 0.0


def test_query_principal_traz_o_orcamento() -> None:
    from src.google_ads.queries.overview import budget_pacing_query

    q, _ = budget_pacing_query(date(2026, 9, 1), date(2026, 9, 28))
    for campo in (
        "campaign_budget.id",
        "campaign_budget.name",
        "campaign_budget.explicitly_shared",
    ):
        assert campo in q


@pytest.mark.parametrize("ids", [[], ["12", "3 OR 1=1"], [str(i) for i in range(1001)]])
def test_query_do_orcamento_recusa_lista_vazia_id_nao_numerico_ou_acima_do_teto(
    ids: list[str],
) -> None:
    from src.google_ads.queries.overview import budget_pacing_orcamentos_query

    with pytest.raises(ValueError):
        gaql, _ = budget_pacing_orcamentos_query(date(2026, 9, 1), date(2026, 9, 28), ids)
