"""Unit tests for src/mcp/tools/_meta_performance.py (Task 3.3 dedup).

Núcleo compartilhado do trio meta_get_{campaign,ad_set,ad}_performance.
Cobre: (a) helper meta_account_not_found_error (mensagem centralizada,
antes duplicada em 5 sites), (b) run_meta_level_performance fim-a-fim com
run_meta_graph_get mockado, parametrizado pelos 3 levels — paridade de shape
entre os 3 é o requisito da task (mesmo caminho de código, então a
parametrização aqui É a prova de paridade).
"""

from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.mcp.tools._meta_performance import (
    meta_account_not_found_error,
    run_meta_level_performance,
)


def test_meta_account_not_found_error_message() -> None:
    err = meta_account_not_found_error("act_404")
    assert err["status"] == "error"
    assert "act_404" in err["error_message"]
    assert "não encontrada" in err["error_message"]
    assert "meta_refresh_accounts" in err["error_message"]
    assert "/oauth/meta/start" in err["error_message"]


class _FakeAcquire:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    async def __aenter__(self) -> Any:
        return self._conn

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakePool:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire(self._conn)


class _FakeAccount:
    account_name = "Conta Teste"
    currency = "BRL"


@pytest.mark.asyncio
async def test_run_meta_level_performance_account_not_found() -> None:
    fake_pool = _FakePool(MagicMock())

    with (
        patch("src.mcp.tools._meta_performance.connection.get_pool", return_value=fake_pool),
        patch(
            "src.mcp.tools._meta_performance.meta_ad_accounts.get_by_id",
            AsyncMock(return_value=None),
        ),
    ):
        result = await run_meta_level_performance(
            level="campaign",
            operation_name="meta_get_campaign_performance",
            manager_id=uuid4(),
            session_id=uuid4(),
            ad_account_id="act_404",
            date_range=None,
            start_date=None,
            end_date=None,
            limit=100,
        )

    assert result["status"] == "error"
    assert "act_404" in result["error_message"]


@pytest.mark.asyncio
async def test_run_meta_level_performance_invalid_dates() -> None:
    """connection.get_pool() é resolvido ANTES da validação de datas (paridade
    com o comportamento pré-dedup dos 3 tools — pool sempre eager, mesmo que a
    validação falhe depois) → precisa de um pool fake mesmo neste caminho."""
    fake_pool = _FakePool(MagicMock())

    with patch("src.mcp.tools._meta_performance.connection.get_pool", return_value=fake_pool):
        result = await run_meta_level_performance(
            level="campaign",
            operation_name="meta_get_campaign_performance",
            manager_id=uuid4(),
            session_id=uuid4(),
            ad_account_id="act_1",
            date_range=None,
            start_date="2026-05-01",  # sem end_date → ValueError
            end_date=None,
            limit=100,
        )
    assert result["status"] == "error"
    assert "Datas inválidas" in result["error_message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("level", ["campaign", "adset", "ad"])
async def test_run_meta_level_performance_success_shape_parity(level: str) -> None:
    """Paridade de shape entre os 3 levels: mesmo envelope de sucesso, rows
    ordenadas por spend_brl desc, independente do level. `operation_name`
    (audit_log) e o `level` passado pro parser são os únicos pontos que variam."""
    fake_pool = _FakePool(MagicMock())
    fake_resp = {
        "data": [
            {"campaign_id": "1", "campaign_name": "A", "spend": "5"},
            {"campaign_id": "2", "campaign_name": "B", "spend": "50"},
        ]
    }
    mock_run_graph_get = AsyncMock(return_value=fake_resp)

    with (
        patch("src.mcp.tools._meta_performance.connection.get_pool", return_value=fake_pool),
        patch(
            "src.mcp.tools._meta_performance.meta_ad_accounts.get_by_id",
            AsyncMock(return_value=_FakeAccount()),
        ),
        patch("src.mcp.tools._meta_performance.run_meta_graph_get", mock_run_graph_get),
    ):
        result = await run_meta_level_performance(
            level=level,  # type: ignore[arg-type]
            operation_name=f"meta_get_{level}_performance",
            manager_id=uuid4(),
            session_id=uuid4(),
            ad_account_id="act_1",
            date_range="LAST_7_DAYS",
            start_date=None,
            end_date=None,
            limit=250,
        )

    # Envelope shape idêntico entre os 3 levels
    assert result["status"] == "success"
    assert result["ad_account_id"] == "act_1"
    assert result["ad_account_name"] == "Conta Teste"
    assert result["currency"] == "BRL"
    # F88: `truncated` entrou no envelope de propósito. A parity desta suíte é
    # com o shape pré-dedup M.3, e a adição é aditiva — nenhum campo saiu. Sem
    # ela, o consumidor não tem como saber que o "top por gasto" pode estar
    # incompleto porque o teto de paginação cortou.
    assert set(result) == {
        "status",
        "ad_account_id",
        "ad_account_name",
        "currency",
        "date_range",
        "rows",
        "total_rows",
        "truncated",
    }
    assert result["total_rows"] == 2
    # Ordenado por spend_brl desc — independente do level
    assert result["rows"][0]["spend_brl"] == 50.0
    assert result["rows"][1]["spend_brl"] == 5.0

    # run_meta_graph_get chamado com o operation_name + level corretos pro audit
    mock_run_graph_get.assert_awaited_once()
    call_kwargs = mock_run_graph_get.call_args.kwargs
    assert call_kwargs["operation_name"] == f"meta_get_{level}_performance"
    assert call_kwargs["ad_account_id"] == "act_1"
    assert call_kwargs["audit_this_call"] is True
    assert call_kwargs["params_summary"]["level"] == level


@pytest.mark.asyncio
async def test_run_meta_level_performance_maps_graph_error_to_friendly_message() -> None:
    fake_pool = _FakePool(MagicMock())

    class _BoomError(Exception):
        message = "Erro Meta curado"

    with (
        patch("src.mcp.tools._meta_performance.connection.get_pool", return_value=fake_pool),
        patch(
            "src.mcp.tools._meta_performance.meta_ad_accounts.get_by_id",
            AsyncMock(return_value=_FakeAccount()),
        ),
        patch(
            "src.mcp.tools._meta_performance.run_meta_graph_get",
            AsyncMock(side_effect=_BoomError()),
        ),
    ):
        result = await run_meta_level_performance(
            level="ad",
            operation_name="meta_get_ad_performance",
            manager_id=uuid4(),
            session_id=uuid4(),
            ad_account_id="act_1",
            date_range=None,
            start_date=None,
            end_date=None,
            limit=100,
        )

    assert result == {"status": "error", "error_message": "Erro Meta curado"}


@pytest.mark.asyncio
async def test_run_meta_level_performance_defaults_to_last_30_days() -> None:
    """date_range=None (sem preset explícito) → default LAST_30_DAYS, não LAST_7_DAYS
    (o trio de performance usa 30 dias default, diferente do account_overview)."""
    fake_pool = _FakePool(MagicMock())
    mock_run_graph_get = AsyncMock(return_value={"data": []})

    with (
        patch("src.mcp.tools._meta_performance.connection.get_pool", return_value=fake_pool),
        patch(
            "src.mcp.tools._meta_performance.meta_ad_accounts.get_by_id",
            AsyncMock(return_value=_FakeAccount()),
        ),
        patch("src.mcp.tools._meta_performance.run_meta_graph_get", mock_run_graph_get),
        patch(
            "src.mcp.tools._meta_performance.datetime",
        ) as mock_datetime,
    ):
        mock_datetime.now.return_value.date.return_value = date(2026, 6, 30)
        result = await run_meta_level_performance(
            level="campaign",
            operation_name="meta_get_campaign_performance",
            manager_id=uuid4(),
            session_id=uuid4(),
            ad_account_id="act_1",
            date_range=None,
            start_date=None,
            end_date=None,
            limit=100,
        )

    assert result["date_range"]["start"] == "2026-06-01"
    assert result["date_range"]["end"] == "2026-06-30"
