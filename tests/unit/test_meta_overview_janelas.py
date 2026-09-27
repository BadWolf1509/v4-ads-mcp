"""O overview Meta diz as duas janelas e se a atual inclui o dia corrente (F195).

O comparativo põe a janela atual contra a anterior de mesma duração. A resposta ecoava só
a atual, e nada dizia quando ela tinha o dia de hoje, que ainda não fechou — o caso em
que a variação compara um dia parcial com dias cheios.
"""

from contextlib import ExitStack
from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.mcp.tools.meta_get_account_overview import meta_get_account_overview

_MODULO = "src.mcp.tools.meta_get_account_overview"
_HOJE = date(2026, 9, 27)


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
    account_status = 1


async def _overview(**janela: str) -> dict[str, Any]:
    with ExitStack() as pilha:
        pilha.enter_context(patch(f"{_MODULO}.connection.get_pool", return_value=_Pool()))
        pilha.enter_context(
            patch(f"{_MODULO}.meta_ad_accounts.get_by_id", AsyncMock(return_value=_Conta()))
        )
        pilha.enter_context(
            patch(
                f"{_MODULO}.run_meta_graph_get",
                AsyncMock(return_value={"data": [{"spend": "10"}]}),
            )
        )
        pilha.enter_context(
            patch(f"{_MODULO}.resolve_meta_account_today", AsyncMock(return_value=_HOJE))
        )
        resultado = await meta_get_account_overview(
            uuid4(), uuid4(), ad_account_id="act_1", **janela
        )
    assert resultado["status"] == "success", resultado
    return resultado


@pytest.mark.asyncio
async def test_preset_compara_dias_completos_e_ecoa_as_duas_janelas() -> None:
    r = await _overview(date_range="LAST_7_DAYS")
    assert r["date_range"] == {"start": "2026-09-20", "end": "2026-09-26"}
    assert r["previous_date_range"] == {"start": "2026-09-13", "end": "2026-09-19"}
    assert r["inclui_dia_corrente"] is False


@pytest.mark.asyncio
async def test_today_avisa_que_o_dia_ainda_nao_fechou() -> None:
    r = await _overview(date_range="TODAY")
    assert r["date_range"] == {"start": "2026-09-27", "end": "2026-09-27"}
    assert r["previous_date_range"] == {"start": "2026-09-26", "end": "2026-09-26"}
    assert r["inclui_dia_corrente"] is True


@pytest.mark.asyncio
async def test_janela_custom_que_termina_hoje_tambem_avisa() -> None:
    r = await _overview(start_date="2026-09-21", end_date="2026-09-27")
    assert r["previous_date_range"] == {"start": "2026-09-14", "end": "2026-09-20"}
    assert r["inclui_dia_corrente"] is True


@pytest.mark.asyncio
async def test_janela_toda_no_futuro_nao_contem_hoje() -> None:
    """O campo diz se a janela CONTEM hoje — terminar depois de hoje nao basta."""
    r = await _overview(start_date="2026-09-28", end_date="2026-09-30")
    assert r["inclui_dia_corrente"] is False
