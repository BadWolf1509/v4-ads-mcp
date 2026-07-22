"""Unit tests for DB pool resilience (src/db/connection.py).

Guards the fix for the intermittent /mcp 500 (mcp_auth_error): Cloud Run keeps
pooled asyncpg connections idle; Supabase eventually closes the socket; the next
request grabbed the dead connection and the auth query raised
ConnectionResetError / ConnectionDoesNotExistError. run_with_reconnect
re-acquires a FRESH connection and retries the (idempotent) op.
"""

from __future__ import annotations

import asyncpg
import pytest

from src.db import connection


class _FakeAcquire:
    def __init__(self, conn: object) -> None:
        self._conn = conn

    async def __aenter__(self) -> object:
        return self._conn

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakePool:
    """Minimal stand-in for asyncpg.Pool: hands out connections in sequence and
    counts acquisitions so a test can assert a *fresh* acquire happened on retry."""

    def __init__(self, conns: list[object]) -> None:
        self._conns = conns
        self.acquires = 0

    def acquire(self) -> _FakeAcquire:
        conn = self._conns[self.acquires]
        self.acquires += 1
        return _FakeAcquire(conn)


async def test_run_with_reconnect_recovers_from_dropped_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dropped pooled connection (ConnectionDoesNotExistError — the exact
    production failure) is retried on a fresh acquire, and the op then succeeds."""
    pool = _FakePool([object(), object()])
    monkeypatch.setattr(connection, "_pool", pool)

    calls = {"n": 0}

    async def op(conn: object) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise asyncpg.exceptions.ConnectionDoesNotExistError(
                "connection was closed in the middle of operation"
            )
        return "resolved"

    result = await connection.run_with_reconnect(op)

    assert result == "resolved"
    assert pool.acquires == 2  # re-acquired a FRESH connection, not the dead one
    assert calls["n"] == 2


async def test_run_with_reconnect_does_not_retry_application_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-connection errors (e.g. an auth rejection) propagate immediately — no retry."""
    pool = _FakePool([object(), object()])
    monkeypatch.setattr(connection, "_pool", pool)

    calls = {"n": 0}

    async def op(conn: object) -> str:
        calls["n"] += 1
        raise ValueError("business rule violated")

    with pytest.raises(ValueError, match="business rule"):
        await connection.run_with_reconnect(op)

    assert pool.acquires == 1  # no retry on a non-connection error
    assert calls["n"] == 1


async def test_run_with_reconnect_reraises_after_exhausting_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If every attempt hits a reset connection, the last error is re-raised (no infinite loop)."""
    pool = _FakePool([object(), object(), object()])
    monkeypatch.setattr(connection, "_pool", pool)

    async def op(conn: object) -> str:
        raise ConnectionResetError(104, "Connection reset by peer")

    with pytest.raises(ConnectionError):
        await connection.run_with_reconnect(op, attempts=2)

    assert pool.acquires == 2  # exactly `attempts` tries


async def test_init_pool_bounds_inactive_connection_lifetime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pool must reap idle connections BEFORE the remote (Supabase) closes
    them — i.e. below asyncpg's 300s default, which the remote can beat."""
    captured: dict[str, object] = {}

    async def fake_create_pool(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(connection.asyncpg, "create_pool", fake_create_pool)
    monkeypatch.setattr(connection, "_pool", None)

    await connection.init_pool("postgresql://ignored")

    lifetime = captured["max_inactive_connection_lifetime"]
    assert lifetime == connection._MAX_INACTIVE_CONNECTION_LIFETIME
    assert 0 < connection._MAX_INACTIVE_CONNECTION_LIFETIME < 300.0
