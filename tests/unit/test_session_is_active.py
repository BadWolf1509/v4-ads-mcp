"""Unit test — resolve_session_to_context raises UnauthorizedError for inactive manager.

FIX 2: is_active check must gate MCP access even when session token is valid.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.mcp.session import UnauthorizedError
from tests.unit.test_manager_deactivation_gate import make_manager


@dataclass
class _FakeSession:
    id: object
    manager_id: object


@pytest.mark.asyncio
async def test_resolve_session_raises_when_manager_inactive():
    from src.mcp.session import resolve_session_to_context

    session_id = uuid4()
    manager_id = uuid4()
    fake_session = _FakeSession(id=session_id, manager_id=manager_id)
    # F84: Manager REAL — o fake so tinha `is_active` e nao conseguia sequer
    # expressar a divergencia com `status` que abriu o buraco.
    fake_manager = make_manager(is_active=False)

    mock_pool = MagicMock()
    mock_conn_cm = MagicMock()
    mock_conn_cm.__aenter__ = AsyncMock(return_value=MagicMock())
    mock_conn_cm.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value = mock_conn_cm

    with (
        patch("src.mcp.session.connection.get_pool", return_value=mock_pool),
        patch(
            "src.mcp.session.mcp_sessions.find_by_hash",
            AsyncMock(return_value=fake_session),
        ),
        patch(
            "src.mcp.session.managers.get_by_id",
            AsyncMock(return_value=fake_manager),
        ),
        pytest.raises(UnauthorizedError, match="inactive"),
    ):
        await resolve_session_to_context("Bearer sometoken")


@pytest.mark.asyncio
async def test_resolve_session_raises_when_manager_not_found():
    from src.mcp.session import resolve_session_to_context

    session_id = uuid4()
    manager_id = uuid4()
    fake_session = _FakeSession(id=session_id, manager_id=manager_id)

    mock_pool = MagicMock()
    mock_conn_cm = MagicMock()
    mock_conn_cm.__aenter__ = AsyncMock(return_value=MagicMock())
    mock_conn_cm.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value = mock_conn_cm

    with (
        patch("src.mcp.session.connection.get_pool", return_value=mock_pool),
        patch(
            "src.mcp.session.mcp_sessions.find_by_hash",
            AsyncMock(return_value=fake_session),
        ),
        patch(
            "src.mcp.session.managers.get_by_id",
            AsyncMock(return_value=None),
        ),
        pytest.raises(UnauthorizedError, match="inactive"),
    ):
        await resolve_session_to_context("Bearer sometoken")
