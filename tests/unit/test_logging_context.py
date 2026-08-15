"""Unit test — resolve_session_to_context (src/mcp/session.py) plugs manager_id/
session_id into structlog contextvars via bind_request_context (src/logging.py).

Onda 1 (2026-06-20): bind_request_context/clear_request_context existiam em
src/logging.py mas estavam órfãos (nunca chamados) — nenhum log em produção
carregava manager_id/session_id. O fix plugou as duas funções em
resolve_session_to_context. Este teste trava a regressão: se alguém remover a
chamada a bind_request_context (ou o clear_request_context do topo), os logs
voltam a sair sem identidade do gestor sem nenhum teste acusar.

Padrão de mocks espelha tests/unit/test_session_is_active.py (mock do pool +
mcp_sessions.find_by_hash + managers.get_by_id).
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import structlog

from src.mcp.context import clear_current
from src.mcp.session import resolve_session_to_context
from tests.unit.test_manager_deactivation_gate import make_manager


@dataclass
class _FakeSession:
    id: object
    manager_id: object


def _mock_pool() -> MagicMock:
    mock_pool = MagicMock()
    mock_conn_cm = MagicMock()
    mock_conn_cm.__aenter__ = AsyncMock(return_value=AsyncMock())
    mock_conn_cm.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value = mock_conn_cm
    return mock_pool


@pytest.fixture(autouse=True)
def _clean_context():
    """Garante contextvars limpos entre testes (structlog usa ContextVar por task)."""
    structlog.contextvars.clear_contextvars()
    yield
    structlog.contextvars.clear_contextvars()
    clear_current()


@pytest.mark.asyncio
async def test_successful_resolution_binds_manager_and_session_to_log_context():
    """Happy path: após resolve_session_to_context, get_contextvars() contém
    manager_id/session_id (strings) — todo log subsequente no request carrega a
    identidade do gestor."""
    session_id = uuid4()
    manager_id = uuid4()
    fake_session = _FakeSession(id=session_id, manager_id=manager_id)
    fake_manager = make_manager()

    with (
        patch("src.mcp.session.connection.get_pool", return_value=_mock_pool()),
        patch(
            "src.mcp.session.mcp_sessions.find_by_hash",
            AsyncMock(return_value=fake_session),
        ),
        patch(
            "src.mcp.session.managers.get_by_id",
            AsyncMock(return_value=fake_manager),
        ),
        patch(
            "src.mcp.session.mcp_sessions.touch_last_used",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.mcp.session.managers.touch_last_seen",
            AsyncMock(return_value=None),
        ),
    ):
        ctx = await resolve_session_to_context("Bearer sometoken")

    bound = structlog.contextvars.get_contextvars()
    assert bound["manager_id"] == str(manager_id)
    assert bound["session_id"] == str(session_id)
    # A context devolvida (McpRequestContext) usa os mesmos ids não-stringificados.
    assert ctx.manager_id == manager_id
    assert ctx.session_id == session_id


@pytest.mark.asyncio
async def test_clears_stale_context_before_binding_new_one():
    """clear_request_context() no topo apaga contextvars de uma chamada anterior
    (ex.: leaked_field de outro request) antes de bindar manager_id/session_id novos
    — sem isto, contextvars vazariam entre requests na mesma async task."""
    structlog.contextvars.bind_contextvars(leaked_field="from_previous_request")

    session_id = uuid4()
    manager_id = uuid4()
    fake_session = _FakeSession(id=session_id, manager_id=manager_id)
    fake_manager = make_manager()

    with (
        patch("src.mcp.session.connection.get_pool", return_value=_mock_pool()),
        patch(
            "src.mcp.session.mcp_sessions.find_by_hash",
            AsyncMock(return_value=fake_session),
        ),
        patch(
            "src.mcp.session.managers.get_by_id",
            AsyncMock(return_value=fake_manager),
        ),
        patch(
            "src.mcp.session.mcp_sessions.touch_last_used",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.mcp.session.managers.touch_last_seen",
            AsyncMock(return_value=None),
        ),
    ):
        await resolve_session_to_context("Bearer sometoken")

    bound = structlog.contextvars.get_contextvars()
    assert "leaked_field" not in bound
    assert bound["manager_id"] == str(manager_id)


@pytest.mark.asyncio
async def test_missing_bearer_raises_without_binding_context():
    """Sem Authorization header -> UnauthorizedError ANTES de qualquer bind (não
    há manager/session pra bindar); contextvars seguem vazios."""
    from src.mcp.session import UnauthorizedError

    with pytest.raises(UnauthorizedError):
        await resolve_session_to_context(None)

    bound = structlog.contextvars.get_contextvars()
    assert "manager_id" not in bound
    assert "session_id" not in bound
