"""asyncpg connection pool factory."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from types import TracebackType
from typing import Any

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


# O `SELECT 1` da retirada custa uma ida e volta (medido em produção em 29/09: +7 ms no p50
# do /health?deep=1). 2 s é folga de ~300x, e cabe duas vezes nos 5 s do health profundo.
_TIMEOUT_DO_TESTE = 2.0


class ConexaoSemRespostaError(ConnectionError):
    """O `SELECT 1` da retirada não voltou no prazo: socket que não responde nem fecha.

    Subclasse de `ConnectionError`, então entra em `_DROPPED_CONNECTION_ERRORS`: a retirada
    é repetida numa conexão nova, como na conexão derrubada.
    """


async def _testa_conexao(conn: asyncpg.Connection) -> None:
    """`setup` do pool: roda a cada retirada, antes de a conexão chegar ao chamador.

    O asyncpg não testa a conexão ociosa (F76), e o Supabase fecha o socket: sem isto, a
    primeira query do chamador é quem descobre. Se o `SELECT 1` falha, o asyncpg fecha a
    conexão e repassa o erro; o `PoolValidado` então retira de novo, e a próxima retirada
    reconecta (spec 2026-09-28 §3.1).

    Socket buraco-negro (não responde e não fecha): sem prazo próprio, o teste herdava os 30 s
    do `command_timeout`, e nem isso — no estouro o asyncpg pede o cancelamento e o `close()`
    gracioso que o pool chama espera, sem prazo, a resposta dele pelo mesmo socket mudo.
    Medido com asyncpg 0.31 e um proxy que para de repassar bytes: a retirada seguia presa
    aos 75 s. Por isso o prazo curto e o `terminate()`, que aborta o transporte sem esperar
    nada; o `close()` do pool vê a conexão fechada e só limpa.
    """
    try:
        await conn.execute("SELECT 1", timeout=_TIMEOUT_DO_TESTE)
    except TimeoutError as exc:
        conn.terminate()
        raise ConexaoSemRespostaError(
            f"SELECT 1 da retirada sem resposta em {_TIMEOUT_DO_TESTE:g} s"
        ) from exc


# A conexão que sai do corpo assim pode estar no meio de um cancelamento (ver
# `_RetiradaValidada`): descartada, não devolvida.
_SAIDAS_QUE_DESCARTAM: tuple[type[BaseException], ...] = (TimeoutError, asyncio.CancelledError)


class _RetiradaValidada:
    """`async with pool.acquire() as conn`, com a retirada repetida uma vez.

    Usa o protocolo de gerenciador de contexto da retirada do asyncpg (e dos fakes dos
    testes), não `await pool.acquire()`. Só a RETIRADA é repetida: um erro dentro do corpo
    do `with` — a query do chamador — sobe sem repetição, então escrita nunca roda duas vezes.

    Na devolução, a conexão que sai do corpo por timeout ou cancelamento é DESCARTADA
    (`terminate()`) antes de voltar ao pool — o padrão de descartar conexão devolvida em estado
    duvidoso (o `psycopg_pool` faz o mesmo; o asyncpg, quando o reset falha). Ela pode estar
    no meio de um cancelamento, e a devolução do asyncpg espera o fim dele sem prazo, sob
    `shield`: num socket mudo, para sempre. Medido em 29/09 com asyncpg 0.31: presa aos 90 s,
    e com `asyncio.timeout` em volta (o formato do /health?deep=1) quem chamou ficava preso
    junto, e a vaga do pool, perdida. Custa reabrir uma conexão saudável cuja query estourou
    ou foi cancelada — raro.
    """

    def __init__(self, pool: Any) -> None:
        self._pool = pool
        self._retirada: Any = None
        self._conn: Any = None

    async def __aenter__(self) -> asyncpg.Connection:
        for tentativa in (1, 2):
            retirada = self._pool.acquire()
            try:
                conn = await retirada.__aenter__()
            except _DROPPED_CONNECTION_ERRORS as exc:
                if tentativa == 2:
                    raise
                log.warning("db_conexao_testada_reconectou", error=str(exc))
                continue
            self._retirada = retirada
            self._conn = conn
            return conn
        raise AssertionError("inalcançável: a 2ª tentativa devolve ou levanta")

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        if exc_type is not None and issubclass(exc_type, _SAIDAS_QUE_DESCARTAM):
            self._conn.terminate()
        return await self._retirada.__aexit__(exc_type, exc, tb)  # type: ignore[no-any-return]


class PoolValidado:
    """O pool que `get_pool()` devolve: a conexão é testada na retirada (spec 2026-09-28 §3.1).

    Só `acquire()` é exposto, de propósito: um atalho do asyncpg (`pool.fetch`,
    `pool.execute`) retiraria por dentro, sem a repetição. O ciclo de vida é do
    `close_pool()`, que também zera o global (um `close()` aqui deixaria `_pool` apontando
    para um pool fechado, e o `init_pool` seguinte o devolveria).
    """

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    def acquire(self) -> _RetiradaValidada:
        return _RetiradaValidada(self._pool)


# F92 — defaults conservadores do pool. Ver docstring de init_pool pra conta
# (instâncias × pool ≤ teto do banco). Settings espelha estes valores pro caminho
# que serve tráfego; um teste garante que os dois não divergem.
DEFAULT_POOL_MIN_SIZE = 1
DEFAULT_POOL_MAX_SIZE = 5


async def init_pool(
    database_url: str,
    min_size: int = DEFAULT_POOL_MIN_SIZE,
    max_size: int = DEFAULT_POOL_MAX_SIZE,
) -> None:
    """Create the global pool. Call once at app startup.

    Não devolve o pool, de propósito (spec 2026-09-28 §3.1): o objeto do asyncpg é o pool
    CRU, e quem o usasse escaparia da repetição da retirada. A única porta é `get_pool()`.

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
        return
    _pool = await asyncpg.create_pool(
        dsn=database_url,
        min_size=min_size,
        max_size=max_size,
        command_timeout=30,
        max_inactive_connection_lifetime=_MAX_INACTIVE_CONNECTION_LIFETIME,
        setup=_testa_conexao,
    )
    log.info("db_pool_created", min_size=min_size, max_size=max_size)


async def close_pool() -> None:
    """Close the global pool. Call once at app shutdown."""
    global _pool
    if _pool is None:
        return
    await _pool.close()
    _pool = None
    log.info("db_pool_closed")


def get_pool() -> PoolValidado:
    """O pool global, com a conexão testada na retirada. Levanta se `init_pool` não rodou."""
    if _pool is None:
        raise RuntimeError("DB pool not initialized; call init_pool() first")
    return PoolValidado(_pool)


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
