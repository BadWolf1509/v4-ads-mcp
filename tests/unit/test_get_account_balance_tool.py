"""get_account_balance: fluxo das duas consultas, erro de permissao e janela de gasto."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.google_ads.errors import GoogleAdsFriendlyError
from src.mcp.context import McpRequestContext, clear_current, set_current
from src.mcp.tools import get_account_balance as modulo

_CONTA = "1234567890"
_HOJE = date(2026, 10, 28)


@pytest.fixture(autouse=True)
def _ctx() -> Iterator[None]:
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _patches(side_effect: Any) -> Any:
    rr = AsyncMock(side_effect=side_effect)
    return (
        rr,
        patch.object(modulo, "run_report", rr),
        patch.object(modulo, "resolve_account_today", AsyncMock(return_value=_HOJE)),
    )


@pytest.mark.asyncio
async def test_authorization_error_vira_indeterminada() -> None:
    rr, p1, p2 = _patches(GoogleAdsFriendlyError("x", code="AUTHORIZATION_ERROR"))
    with p1, p2:
        resp = await modulo.get_account_balance({"customer_id": _CONTA})
    assert resp["situacao"] == "indeterminada"
    assert resp["motivo"] == "sem permissão de faturamento nesta conta"
    assert rr.await_count == 1


@pytest.mark.asyncio
async def test_outro_erro_sobe() -> None:
    _, p1, p2 = _patches(GoogleAdsFriendlyError("x", code="QUOTA_ERROR"))
    with p1, p2, pytest.raises(GoogleAdsFriendlyError):
        await modulo.get_account_balance({"customer_id": _CONTA})


@pytest.mark.asyncio
async def test_as_duas_consultas_auditam() -> None:
    rr, p1, p2 = _patches([[], []])
    with p1, p2:
        await modulo.get_account_balance({"customer_id": _CONTA})
    assert rr.await_count == 2
    assert all(c.kwargs["audit_this_call"] is True for c in rr.await_args_list)
    assert all(c.kwargs["operation_name"] == "get_account_balance" for c in rr.await_args_list)


@pytest.mark.asyncio
async def test_janela_de_gasto_termina_ontem_no_fuso_da_conta() -> None:
    rr, p1, p2 = _patches([[], []])
    with p1, p2:
        resp = await modulo.get_account_balance({"customer_id": _CONTA})
    gaql = rr.await_args_list[1].kwargs["query"]
    assert "2026-09-28" in gaql and "2026-10-27" in gaql
    assert resp["period"] == {"from": "2026-09-28", "to": "2026-10-27"}
