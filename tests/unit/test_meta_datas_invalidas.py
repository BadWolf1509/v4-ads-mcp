"""Data invalida nas 3 tools Meta que resolvem janela: UMA mensagem (Task D3).

Antes, o overview dizia "Parametros de data invalidos" e as outras duas "Datas
invalidas". O dado e o mesmo; a mensagem ao gestor tambem tem que ser. O fuso da
conta e mockado em `_timezone_name` (fonte do relogio), nao no nome importado em
cada tool, para o teste nao depender de onde a resolucao mora.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.mcp.tools._meta_performance import run_meta_level_performance
from src.mcp.tools.meta_get_account_overview import meta_get_account_overview
from src.mcp.tools.meta_get_performance_breakdown import meta_get_performance_breakdown

_DETALHE = "start_date e end_date devem ser fornecidos juntos"


async def _overview(**kw: Any) -> dict[str, Any]:
    return await meta_get_account_overview(uuid4(), uuid4(), ad_account_id="act_1", **kw)


async def _breakdown(**kw: Any) -> dict[str, Any]:
    return await meta_get_performance_breakdown(
        uuid4(), uuid4(), ad_account_id="act_1", breakdown="platform", **kw
    )


async def _nivel(**kw: Any) -> dict[str, Any]:
    return await run_meta_level_performance(
        level="campaign",
        operation_name="meta_get_campaign_performance",
        manager_id=uuid4(),
        session_id=uuid4(),
        ad_account_id="act_1",
        date_range=None,
        end_date=None,
        limit=10,
        **kw,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("chamar", [_overview, _breakdown, _nivel])
async def test_data_invalida_tem_a_mesma_mensagem_nas_tres_tools(chamar: Any) -> None:
    kw: dict[str, Any] = {"start_date": "2026-05-01"}  # sem end_date
    if chamar is _overview or chamar is _breakdown:
        kw["end_date"] = None
    with (
        patch("src.db.connection.get_pool", return_value=MagicMock()),
        patch("src.meta_ads.account_clock._timezone_name", AsyncMock(return_value=None)),
    ):
        resultado = await chamar(**kw)
    assert resultado == {"status": "error", "error_message": f"Datas inválidas: {_DETALHE}"}
