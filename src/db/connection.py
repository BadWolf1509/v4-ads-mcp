"""asyncpg connection pool factory."""

from collections.abc import AsyncIterator, Awaitable, Callable

import asyncpg
import structlog

log = structlog.get_logger(__name__)

_pool: asyncpg.Pool | None = None

# Reap idle pooled connections BEFORE the remote (Supabase/PgBouncer) closes the
# socket. asyncpg's default is 300s; the remote can close idle connections sooner,
# so we bound it lower to shrink the window where a dead connection is handed out.
_MAX_INACTIVE_CONNECTION_LIFETIME = 120.0

# A pooled connection the remote closed while idle surfaces as one of these when
# the NEXT query runs (statement prep fails). Safe to retry on a FRESH connection
# for idempotent ops — the statement never executed.
_DROPPED_CONNECTION_ERRORS: tuple[type[BaseException], ...] = (
    asyncpg.PostgresConnectionError,  # ConnectionDoesNotExistError, ConnectionFailureError
    ConnectionError,  # builtin: ConnectionResetError [Errno 104], BrokenPipeError, ...
)


# F92 — defaults conservadores do pool. Ver docstring de init_pool pra conta
# (instâncias × pool ≤ teto do banco). Settings espelha estes valores pro caminho
# que serve tráfego; um teste garante que os dois não divergem.
DEFAULT_POOL_MIN_SIZE = 1
DEFAULT_POOL_MAX_SIZE = 5


async def init_pool(
    database_url: str,
    min_size: int = DEFAULT_POOL_MIN_SIZE,
    max_size: int = DEFAULT_POOL_MAX_SIZE,
) -> asyncpg.Pool:
    """Create the global pool. Call once at app startup.

    F92 — o default caiu de 10 pra 5. O orçamento é **instâncias × pool** e tem
    que caber no teto do banco: com `--max-instances=10`, o antigo default
    permitia 100 conexões contra as 60 de um tier pequeno do Supabase, e `too
    many connections` derruba o deep health e as tools em cascata.

    Este módulo NÃO lê `Settings` de propósito: é um primitivo de banco, e
    acoplá-lo à config completa da app quebra quem o usa sem as 13 variáveis
    obrigatórias — foi exatamente o que derrubou a suíte de integração na 1ª
    tentativa deste fix. Quem serve tráfego (`app.py`) passa
    `settings.db_pool_*` explicitamente, que é onde a conta de instâncias
    importa; job e script ficam com o default conservador.
    """
    global _pool
    if _pool is not None:
        return _pool
    _pool = await asyncpg.create_pool(
        dsn=database_url,
        min_size=min_size,
        max_size=max_size,
        command_timeout=30,
        max_inactive_connection_lifetime=_MAX_INACTIVE_CONNECTION_LIFETIME,
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


async def run_with_reconnect[T](
    op: Callable[[asyncpg.Connection], Awaitable[T]], *, attempts: int = 2
) -> T:
    """Run ``op(conn)`` with a pooled connection, re-acquiring a FRESH connection
    if the current one was dropped/reset while idle (Cloud Run keeps connections
    idle; Supabase then closes the socket).

    ``op`` MUST be idempotent — it is re-run from scratch on retry. Only
    dropped-connection errors are retried; application errors (e.g.
    ``UnauthorizedError``) and real query errors propagate immediately.
    """
    pool = get_pool()
    last_exc: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            async with pool.acquire() as conn:
                return await op(conn)
        except _DROPPED_CONNECTION_ERRORS as exc:
            last_exc = exc
            if attempt < attempts:
                log.warning("db_dropped_connection_retry", attempt=attempt, error=str(exc))
    assert last_exc is not None  # loop ran ≥1 time and only reaches here after a catch
    raise last_exc
