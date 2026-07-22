"""Unit tests for MCP session resolution (src/mcp/session.py)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import asyncpg
import pytest

from src.db import connection
from src.db.repositories import managers, mcp_sessions
from src.db.repositories.managers import Manager
from src.db.repositories.mcp_sessions import McpSession
from src.mcp.session import extract_bearer_token, resolve_session_to_context


def test_extracts_bearer_from_header() -> None:
    token = extract_bearer_token("Bearer mcp_abc123")
    assert token == "mcp_abc123"


def test_returns_none_for_missing_header() -> None:
    assert extract_bearer_token(None) is None


def test_returns_none_for_wrong_scheme() -> None:
    assert extract_bearer_token("Basic dXNlcjpwYXNz") is None


def test_returns_none_for_empty_token() -> None:
    assert extract_bearer_token("Bearer ") is None


class _Acquire:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _UnlimitedPool:
    """Fake asyncpg pool: yields a throwaway connection per acquire, unbounded."""

    def __init__(self) -> None:
        self.acquires = 0

    def acquire(self) -> _Acquire:
        self.acquires += 1
        return _Acquire()


async def test_resolve_session_recovers_from_dropped_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The production /mcp 500: a pooled connection Supabase closed while idle
    makes the auth lookup raise ConnectionDoesNotExistError. Resolution must
    retry on a fresh connection and succeed. Docker-free (fake pool + mocked repos)."""
    mid, sid = uuid4(), uuid4()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    sess = McpSession(
        id=sid,
        manager_id=mid,
        token_hash="h",
        label="t",
        created_at=now,
        last_used_at=None,
        revoked_at=None,
        expires_at=None,
    )
    mgr = Manager(
        id=mid,
        email="x@v4.com",
        full_name=None,
        role="gestor",
        is_active=True,
        created_at=now,
        last_seen_at=None,
        status="active",
        invited_by=None,
        invited_at=None,
    )

    monkeypatch.setattr(connection, "_pool", _UnlimitedPool())

    find_calls = {"n": 0}

    async def flaky_find(conn: object, token_hash: str) -> McpSession:
        find_calls["n"] += 1
        if find_calls["n"] == 1:
            raise asyncpg.exceptions.ConnectionDoesNotExistError(
                "connection was closed in the middle of operation"
            )
        return sess

    monkeypatch.setattr(mcp_sessions, "find_by_hash", flaky_find)
    monkeypatch.setattr(managers, "get_by_id", AsyncMock(return_value=mgr))
    monkeypatch.setattr(mcp_sessions, "touch_last_used", AsyncMock())
    monkeypatch.setattr(managers, "touch_last_seen", AsyncMock())

    ctx = await resolve_session_to_context("Bearer sometoken")

    assert ctx.manager_id == mid
    assert ctx.session_id == sid
    assert find_calls["n"] == 2  # first attempt dropped → retried on a fresh connection
