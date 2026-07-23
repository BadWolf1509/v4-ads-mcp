import asyncio
import sys

import asyncpg
import pytest
from httpx import AsyncClient

from src.db import connection


class _FakeAcquire:
    def __init__(self, conn: object) -> None:
        self._conn = conn

    async def __aenter__(self) -> object:
        return self._conn

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakePool:
    def __init__(self, conns: list[object]) -> None:
        self._conns = conns
        self.acquires = 0

    def acquire(self) -> _FakeAcquire:
        conn = self._conns[self.acquires]
        self.acquires += 1
        return _FakeAcquire(conn)


class _StaleConnection:
    async def fetchval(self, query: str) -> int:
        assert query == "SELECT 1"
        raise asyncpg.ConnectionDoesNotExistError(
            "connection was closed in the middle of operation"
        )


class _HealthyConnection:
    async def fetchval(self, query: str) -> int:
        assert query == "SELECT 1"
        return 1


class _SlowConnection:
    async def fetchval(self, query: str) -> int:
        assert query == "SELECT 1"
        await asyncio.sleep(0.05)
        return 1


async def test_health_deep_recovers_from_stale_pooled_connection(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = _FakePool([_StaleConnection(), _HealthyConnection()])
    monkeypatch.setattr(connection, "_pool", pool)

    response = await client.get("/health?deep=1")

    assert response.status_code == 200
    assert response.json()["db"] == "ok"
    assert pool.acquires == 2


async def test_health_deep_stays_degraded_when_retry_also_fails(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = _FakePool([_StaleConnection(), _StaleConnection()])
    monkeypatch.setattr(connection, "_pool", pool)

    response = await client.get("/health?deep=1")

    assert response.status_code == 503
    assert response.json()["db"] == "error"
    assert pool.acquires == 2


async def test_health_deep_times_out_before_external_probe(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_module = sys.modules["src.app"]
    pool = _FakePool([_SlowConnection()])
    monkeypatch.setattr(connection, "_pool", pool)
    monkeypatch.setattr(app_module, "_HEALTH_DB_TIMEOUT_SECONDS", 0.01)

    response = await client.get("/health?deep=1")

    assert response.status_code == 503
    assert response.json()["db"] == "error"
    assert pool.acquires == 1
