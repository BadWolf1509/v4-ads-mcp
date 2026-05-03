"""asyncpg connection pool factory."""

from collections.abc import AsyncIterator

import asyncpg
import structlog

log = structlog.get_logger(__name__)

_pool: asyncpg.Pool | None = None


async def init_pool(database_url: str, min_size: int = 1, max_size: int = 10) -> asyncpg.Pool:
    """Create the global pool. Call once at app startup."""
    global _pool
    if _pool is not None:
        return _pool
    _pool = await asyncpg.create_pool(
        dsn=database_url,
        min_size=min_size,
        max_size=max_size,
        command_timeout=30,
    )
    log.info("db_pool_created", min_size=min_size, max_size=max_size)
    return _pool


async def close_pool() -> None:
    """Close the global pool. Call once at app shutdown."""
    global _pool
    if _pool is None:
        return
    await _pool.close()
    _pool = None
    log.info("db_pool_closed")


def get_pool() -> asyncpg.Pool:
    """Get the global pool. Raises if init_pool was not called."""
    if _pool is None:
        raise RuntimeError("DB pool not initialized; call init_pool() first")
    return _pool


async def acquire() -> AsyncIterator[asyncpg.Connection]:
    """FastAPI-compatible dependency that yields a connection."""
    pool = get_pool()
    async with pool.acquire() as conn:
        yield conn
