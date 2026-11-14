"""Lint estatico do GAQL (N1, spec 2026-11-14): `segments.date` no SELECT esconde entidade sem
trafego (medido MO-JP 14/11: 4 campanhas REMOVED sem impressao -> 4 linhas sem data / com data so
no WHERE, 0 linhas com data no SELECT). Analisa so a lista entre SELECT e FROM."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.google_ads.gaql_lint import AVISO_N1, avisos_gaql
from src.mcp.context import McpRequestContext, clear_current, set_current


def test_data_no_select_avisa() -> None:
    q = "SELECT campaign.id, segments.date, metrics.clicks FROM campaign"
    assert avisos_gaql(q) == [AVISO_N1]


def test_data_so_no_where_nao_avisa() -> None:
    q = "SELECT campaign.id FROM campaign WHERE segments.date DURING LAST_7_DAYS"
    assert avisos_gaql(q) == []


def test_data_em_literal_do_where_nao_avisa() -> None:
    q = "SELECT campaign.id FROM campaign WHERE campaign.name = 'segments.date'"
    assert avisos_gaql(q) == []


def test_case_insensitive() -> None:
    assert avisos_gaql("select SEGMENTS.DATE from campaign") == [AVISO_N1]


def test_outro_segmento_nao_avisa() -> None:
    # segments.week/month nao foram medidos: a regra cobre so segments.date.
    assert avisos_gaql("SELECT campaign.id, segments.month FROM campaign") == []
    assert avisos_gaql("SELECT campaign.id, segments.date_foo FROM campaign") == []


def test_copy_fixa_do_aviso() -> None:
    assert AVISO_N1 == (
        "segments.date no SELECT: o Google so devolve linhas de (entidade, dia) com dado — "
        "entidade sem trafego no periodo NAO aparece. Para inventario, tire segments.date do "
        "SELECT; no WHERE ele nao esconde nada (medido em 14/11)."
    )


# ---------- run_gaql: a chave `avisos` existe sempre ----------


@pytest.fixture
def _ctx() -> Iterator[None]:
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


async def _run(query: str, **args: Any) -> dict[str, Any]:
    from src.mcp.tools.run_gaql import run_gaql

    with patch(
        "src.mcp.tools.run_gaql.execute_gaql_raw", AsyncMock(return_value=[{"a": {"b": 1}}])
    ):
        return await run_gaql({"customer_id": "7862230676", "query": query, **args})


@pytest.mark.usefixtures("_ctx")
@pytest.mark.parametrize("extra", [{}, {"compact": True}, {"aggregate_by": ["a.b"]}])
async def test_run_gaql_avisa_data_no_select_em_todos_os_modos(extra: dict[str, Any]) -> None:
    out = await _run("SELECT campaign.id, segments.date FROM campaign", **extra)
    assert out["avisos"] == [AVISO_N1]


@pytest.mark.usefixtures("_ctx")
@pytest.mark.parametrize("extra", [{}, {"compact": True}, {"aggregate_by": ["a.b"]}])
async def test_run_gaql_sem_data_traz_avisos_vazio(extra: dict[str, Any]) -> None:
    out = await _run("SELECT campaign.id FROM campaign", **extra)
    assert out["avisos"] == []


# ---------- validate_gaql ----------


def _pool_with_conn() -> MagicMock:
    fake_conn = AsyncMock()
    txn = MagicMock()
    txn.__aenter__ = AsyncMock(return_value=None)
    txn.__aexit__ = AsyncMock(return_value=None)
    fake_conn.transaction = MagicMock(return_value=txn)
    pool = MagicMock()
    acq = MagicMock()
    acq.__aenter__ = AsyncMock(return_value=fake_conn)
    acq.__aexit__ = AsyncMock(return_value=None)
    pool.acquire.return_value = acq
    return pool


def _client(search: MagicMock) -> MagicMock:
    client = MagicMock()
    service = MagicMock()
    service.search = search
    client.get_service = MagicMock(return_value=service)
    client.get_type = MagicMock(return_value=MagicMock())
    return client


async def _validar(query: str, search: MagicMock) -> dict[str, Any]:
    from src.mcp.tools.validate_gaql import validate_gaql

    pool = _pool_with_conn()
    with (
        patch("src.mcp.tools.validate_gaql.ensure_account_access", AsyncMock(return_value=None)),
        patch("src.mcp.tools.validate_gaql.before_call", AsyncMock()),
        patch("src.mcp.tools.validate_gaql.record_actual", AsyncMock()),
        patch("src.mcp.tools.validate_gaql.audit_log.record", AsyncMock(return_value=1)),
        patch("src.mcp.tools.validate_gaql.connection.get_pool", return_value=pool),
        patch(
            "src.mcp.tools.validate_gaql.build_client_for_manager",
            AsyncMock(return_value=_client(search)),
        ),
    ):
        return await validate_gaql({"customer_id": "1234567890", "query": query})


@pytest.mark.usefixtures("_ctx")
async def test_validate_valido_com_data_no_select_avisa() -> None:
    out = await _validar(
        "SELECT campaign.id, segments.date FROM campaign", MagicMock(return_value=iter([]))
    )
    assert out["valid"] is True
    assert out["avisos"] == [AVISO_N1]


@pytest.mark.usefixtures("_ctx")
async def test_validate_valido_sem_data_traz_avisos_vazio() -> None:
    out = await _validar("SELECT campaign.id FROM campaign", MagicMock(return_value=iter([])))
    assert out["valid"] is True
    assert out["avisos"] == []


@pytest.mark.usefixtures("_ctx")
async def test_validate_invalido_tambem_traz_avisos() -> None:
    out = await _validar(
        "SELECT campaign.id, segments.date FROM campaign",
        MagicMock(side_effect=Exception("Bad GAQL")),
    )
    assert out["valid"] is False
    assert out["avisos"] == [AVISO_N1]
