"""Linha sem `spend` nao derruba a ordenacao do trio nem do breakdown (spec 2026-09-26 §4.1).

O contrato devolve `spend_brl: None` quando a Meta nao manda `spend`, e `None > float`
levanta TypeError. O sort de seguranca das duas tools usa `_gasto_para_ordenar`, que manda
o None para o fim. Os testes passam pelas TOOLS, nao pelo helper: o que quebraria e um
call-site voltar a ordenar por `r["spend_brl"]` (revisao final do F194).
"""

from contextlib import ExitStack
from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.mcp.tools._meta_performance import run_meta_level_performance
from src.mcp.tools.meta_get_performance_breakdown import meta_get_performance_breakdown

_RESPOSTA = {
    "data": [
        {"campaign_id": "1", "campaign_name": "sem gasto"},
        {"campaign_id": "2", "campaign_name": "B", "spend": "50"},
        {"campaign_id": "3", "campaign_name": "C", "spend": "5"},
    ]
}


class _Acquire:
    async def __aenter__(self) -> Any:
        return MagicMock()

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _Pool:
    def acquire(self) -> _Acquire:
        return _Acquire()


class _Conta:
    account_name = "Conta Teste"
    currency = "BRL"


def _dubles(pilha: ExitStack, modulo: str) -> None:
    pilha.enter_context(patch(f"{modulo}.connection.get_pool", return_value=_Pool()))
    pilha.enter_context(
        patch(f"{modulo}.meta_ad_accounts.get_by_id", AsyncMock(return_value=_Conta()))
    )
    pilha.enter_context(patch(f"{modulo}.run_meta_graph_get", AsyncMock(return_value=_RESPOSTA)))
    pilha.enter_context(
        patch(
            f"{modulo}.resolve_meta_account_today",
            AsyncMock(return_value=date(2026, 9, 27)),
        )
    )


def _gastos(resultado: dict[str, Any]) -> list[float | None]:
    assert resultado["status"] == "success", resultado
    return [linha["spend_brl"] for linha in resultado["rows"]]


@pytest.mark.asyncio
async def test_trio_poe_a_linha_sem_gasto_no_fim() -> None:
    with ExitStack() as pilha:
        _dubles(pilha, "src.mcp.tools._meta_performance")
        resultado = await run_meta_level_performance(
            level="campaign",
            operation_name="meta_get_campaign_performance",
            manager_id=uuid4(),
            session_id=uuid4(),
            ad_account_id="act_1",
            date_range="LAST_7_DAYS",
            start_date=None,
            end_date=None,
            limit=100,
        )
    assert _gastos(resultado) == [50.0, 5.0, None]


@pytest.mark.asyncio
async def test_breakdown_poe_a_linha_sem_gasto_no_fim() -> None:
    with ExitStack() as pilha:
        _dubles(pilha, "src.mcp.tools.meta_get_performance_breakdown")
        resultado = await meta_get_performance_breakdown(
            uuid4(), uuid4(), ad_account_id="act_1", breakdown="platform"
        )
    assert _gastos(resultado) == [50.0, 5.0, None]
