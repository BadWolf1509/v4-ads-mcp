"""get_account_balance: fluxo das duas consultas, erro de permissao e janela de gasto."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from types import SimpleNamespace
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
    assert resp["motivo"] == (
        "erro de autorização do Google ao ler o orçamento da conta "
        "(sem permissão de faturamento ou sem acesso à conta)"
    )
    assert rr.await_count == 1
    for campo in (
        "restante_brl",
        "media_diaria_7d_brl",
        "dias_restantes",
        "dias_ate_fim",
        "limite_ajustado_brl",
        "gasto_acumulado_brl",
    ):
        assert resp[campo] is None, campo
    assert resp["aproximado"] is True
    assert resp["customer_id"] == _CONTA
    assert "orcamento" in resp["filters_applied"] and "gasto" in resp["filters_applied"]


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


def _orc(
    tipo: str = "UNSPECIFIED",
    limite: int = 0,
    servido: int = 0,
    fim: str = "",
    pend: str = "",
) -> SimpleNamespace:
    b = SimpleNamespace(
        approved_spending_limit_type=SimpleNamespace(name=tipo),
        adjusted_spending_limit_micros=limite,
        amount_served_micros=servido,
        total_adjustments_micros=0,
        approved_start_date_time="2021-02-26 15:37:54",
        approved_end_date_time=fim,
        approved_end_time_type=SimpleNamespace(name="FOREVER" if not fim else "TIME"),
        pending_proposal=SimpleNamespace(account_budget_proposal=pend),
    )
    return SimpleNamespace(account_budget=b)


def test_formatter_orcamento_finito_sem_fim() -> None:
    r = modulo._row_formatter_orcamento(_orc(limite=34_782_190_000, servido=34_468_970_000))
    assert r["tipo_limite"] == "UNSPECIFIED"
    assert r["limite_ajustado_micros"] == 34_782_190_000
    assert r["gasto_micros"] == 34_468_970_000
    assert r["fim"] is None
    assert r["pendente"] is False
    assert r["tipo_fim"] == "FOREVER"


def test_formatter_orcamento_infinito_sem_limite() -> None:
    r = modulo._row_formatter_orcamento(_orc(tipo="INFINITE", limite=0))
    assert r["tipo_limite"] == "INFINITE"
    assert r["limite_ajustado_micros"] is None


def test_formatter_orcamento_finito_com_limite_zero_fica_zero() -> None:
    r = modulo._row_formatter_orcamento(_orc(limite=0))
    assert r["limite_ajustado_micros"] == 0


def test_formatter_orcamento_com_fim_e_proposta_pendente() -> None:
    r = modulo._row_formatter_orcamento(
        _orc(limite=5, fim="2026-12-31 23:59:59", pend="customers/1/accountBudgetProposals/9")
    )
    assert r["fim"] == "2026-12-31 23:59:59"
    assert r["pendente"] is True


def test_formatter_gasto() -> None:
    row = SimpleNamespace(
        segments=SimpleNamespace(date="2026-10-27"),
        metrics=SimpleNamespace(cost_micros=1_234_560_000),
    )
    assert modulo._row_formatter_gasto(row) == {"data": date(2026, 10, 27), "custo": 1234.56}


@pytest.mark.asyncio
async def test_ponta_a_ponta_com_formatadores_reais_hosp_ocular() -> None:
    linhas_orc = [_orc(limite=34_782_190_000, servido=34_468_970_000)]
    linhas_gasto = [
        SimpleNamespace(
            segments=SimpleNamespace(date="2026-10-27"),
            metrics=SimpleNamespace(cost_micros=10_000_000),
        )
    ]

    async def fake(**kw: Any) -> list[Any]:
        linhas = linhas_orc if "account_budget" in kw["query"] else linhas_gasto
        return [kw["row_formatter"](x) for x in linhas]

    _, p1, p2 = _patches(fake)
    with p1, p2:
        resp = await modulo.get_account_balance({"customer_id": _CONTA})
    assert resp["restante_brl"] == 313.22
    assert resp["situacao"] == "com_saldo"
    assert resp["tipo_de_teto"] == "finito"


def test_descricao_declara_moeda_brl_e_autorizacao() -> None:
    from src.mcp.tools._registry import get_tool, import_all_tools

    import_all_tools()
    tool = get_tool("get_account_balance")
    assert tool is not None
    desc = tool.description
    assert "moeda da conta é BRL" in desc
    assert "sem acesso à conta" in desc
