"""F199: a projecao do `get_budget_pacing` sai dos dias FECHADOS do mes.

Somava o gasto parcial de hoje (`DURING THIS_MONTH` inclui o dia corrente) e dividia
por `today.day`, contando hoje como dia inteiro: a media diaria saia baixa, tanto mais
quanto mais cedo no dia e no mes — exatamente quando a description manda usar a tool.
Medido em 28/09 na Mestre da Obra - Joao Pessoa: -3,6% antes do primeiro gasto do dia;
na manha do dia 1, com R$ 20 gastos, a projecao era R$ 600 contra ~R$ 9.271 do ritmo real.

A janela passa a ser a do `THIS_MONTH` de `janelas.py` (ate ontem; no dia 1, so hoje),
a mesma das outras tools, e o gasto de hoje vem num campo a parte.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from freezegun import freeze_time

from src.mcp.context import McpRequestContext, clear_current, set_current

_CONTA = "1234567890"


@pytest.fixture(autouse=True)
def _ctx() -> Iterator[None]:
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _linha(cid: str, custo_brl: float, orcamento: float = 310.0) -> dict[str, Any]:
    return {
        "campaign_id": cid,
        "campaign_name": f"Camp {cid}",
        "daily_budget_brl": orcamento,
        "delivery_method": "STANDARD",
        "cost_micros": round(custo_brl * 1_000_000),
    }


def _hoje(cid: str, custo_brl: float) -> dict[str, Any]:
    return {"campaign_id": cid, "cost_micros": round(custo_brl * 1_000_000)}


async def _pacing(respostas: list[list[dict[str, Any]]], **args: Any) -> tuple[Any, AsyncMock]:
    from src.mcp.tools.get_budget_pacing import get_budget_pacing

    with patch("src.mcp.tools.get_budget_pacing.run_report", new_callable=AsyncMock) as rr:
        rr.side_effect = respostas
        out = await get_budget_pacing({"customer_id": _CONTA, **args})
    return out, rr


@pytest.mark.asyncio
@freeze_time("2026-09-28 16:28:00")
async def test_projecao_sai_dos_dias_fechados() -> None:
    """Os numeros medidos em 28/09: R$ 8.344,07 em 27 dias fechados, R$ 277,63 hoje."""
    out, _ = await _pacing([[_linha("1", 8344.07)], [_hoje("1", 277.63)]])
    (c,) = out["campaigns"]
    assert c["spent_mtd_brl"] == 8344.07
    assert c["days_elapsed"] == 27
    assert c["days_remaining"] == 3  # hoje ainda esta por gastar
    assert c["projected_monthly_brl"] == round(8344.07 / 27 * 30, 2)  # 9271.19
    assert c["gasto_hoje_brl"] == 277.63
    assert out["inclui_dia_corrente"] is False


@pytest.mark.asyncio
@freeze_time("2026-09-28 16:28:00")
async def test_a_janela_e_a_do_this_month_ate_ontem() -> None:
    out, rr = await _pacing([[_linha("1", 100.0)], [_hoje("1", 5.0)]])
    principal = rr.await_args_list[0].kwargs["query"]
    assert "segments.date BETWEEN '2026-09-01' AND '2026-09-27'" in principal
    assert "DURING" not in principal
    assert out["period"] == {"from": "2026-09-01", "to": "2026-09-27"}
    assert out["filters_applied"]["date_range"] == {"start": "2026-09-01", "end": "2026-09-27"}


@pytest.mark.asyncio
@freeze_time("2026-10-01 11:00:00")
async def test_dia_um_nao_projeta() -> None:
    """Sem dia fechado nao ha media: projecao indefinida, nao 30x o parcial."""
    out, rr = await _pacing([[_linha("1", 20.0)]])
    (c,) = out["campaigns"]
    assert c["projected_monthly_brl"] is None
    assert c["projection_vs_budget_pct"] is None
    assert c["days_elapsed"] == 0
    assert c["days_remaining"] == 31
    # a janela do dia 1 e so hoje (F196): o gasto do mes E o de hoje, sem 2a query
    assert c["spent_mtd_brl"] == 20.0
    assert c["gasto_hoje_brl"] == 20.0
    assert out["inclui_dia_corrente"] is True
    assert rr.await_count == 1
    assert "BETWEEN '2026-10-01' AND '2026-10-01'" in rr.await_args_list[0].kwargs["query"]


@pytest.mark.asyncio
@freeze_time("2026-09-28 16:28:00")
async def test_gasto_de_hoje_so_das_campanhas_listadas() -> None:
    out, rr = await _pacing(
        [[_linha("111", 900.0), _linha("222", 300.0)], [_hoje("111", 40.0)]],
    )
    hoje = rr.await_args_list[1].kwargs["query"]
    assert "campaign.id IN (111, 222)" in hoje
    assert "segments.date BETWEEN '2026-09-28' AND '2026-09-28'" in hoje
    por_id = {c["campaign_id"]: c for c in out["campaigns"]}
    assert por_id["111"]["gasto_hoje_brl"] == 40.0
    # a query de hoje rodou e nao trouxe linha: gasto zero MEDIDO, nao ausencia
    assert por_id["222"]["gasto_hoje_brl"] == 0.0


@pytest.mark.asyncio
@freeze_time("2026-09-28 16:28:00")
async def test_sem_campanha_nao_roda_a_query_de_hoje() -> None:
    out, rr = await _pacing([[]])
    assert out["campaigns"] == []
    assert rr.await_count == 1


@pytest.mark.parametrize("ids", [[], ["12", "3 OR 1=1"], [str(i) for i in range(1001)]])
def test_query_de_hoje_recusa_lista_vazia_id_nao_numerico_ou_acima_do_teto(ids: list[str]) -> None:
    from datetime import date

    from src.google_ads.queries.overview import budget_pacing_hoje_query

    with pytest.raises(ValueError):
        gaql, _ = budget_pacing_hoje_query(date(2026, 9, 28), ids)
