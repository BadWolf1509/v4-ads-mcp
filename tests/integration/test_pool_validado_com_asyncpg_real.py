"""A premissa da Parte 1 medida com asyncpg real (spec 2026-09-28 §3.1; revisão final, I3).

Os testes unitários de `test_pool_validado.py` usam um pool falso que JÁ levanta o erro na
retirada — supõem o que o asyncpg faz. Aqui a falha é a de produção (F76): o outro lado
derruba a conexão ociosa e o cliente só descobre na próxima escrita. Um proxy TCP no próprio
processo, entre o pool e o Postgres do container, corta as conexões marcadas assim que o
cliente escreve nelas. Três comportamentos do asyncpg sustentam o desenho, e é isto que os
guarda contra uma troca de versão (o `pyproject.toml` aceita `asyncpg>=0.30.0`):

1. o erro do `setup` (o `SELECT 1`) sobe da retirada, não é engolido;
2. o holder fecha a conexão e volta à fila;
3. a fila é LIFO, então a 2ª retirada pega o mesmo holder, agora vazio, e reconecta.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest

from src.db import connection


class _ProxyQueDerruba:
    """Repassa bytes ao Postgres; as conexões condenadas morrem na próxima escrita do cliente."""

    def __init__(self, host: str, porta: int) -> None:
        self._destino = (host, porta)
        self._abertas: set[asyncio.StreamWriter] = set()
        self._condenadas: set[asyncio.StreamWriter] = set()
        self.porta = 0
        self.aceitas = 0  # conexões que o pool abriu através do proxy

    async def __aenter__(self) -> _ProxyQueDerruba:
        self._servidor = await asyncio.start_server(self._atender, "127.0.0.1", 0)
        self.porta = self._servidor.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._servidor.close()
        for w in list(self._abertas):
            w.transport.abort()
        await self._servidor.wait_closed()

    def derrubar_as_ociosas(self) -> int:
        self._condenadas |= self._abertas
        return len(self._abertas)

    async def _atender(self, r_cli: asyncio.StreamReader, w_cli: asyncio.StreamWriter) -> None:
        r_srv, w_srv = await asyncio.open_connection(*self._destino)
        self._abertas.add(w_cli)
        self.aceitas += 1

        async def cliente_para_banco() -> None:
            while dados := await r_cli.read(65536):
                if w_cli in self._condenadas:
                    w_cli.transport.abort()
                    w_srv.transport.abort()
                    return
                w_srv.write(dados)
                await w_srv.drain()
            w_srv.close()  # o cliente fechou: o banco fica sabendo

        async def banco_para_cliente() -> None:
            while dados := await r_srv.read(65536):
                w_cli.write(dados)
                await w_cli.drain()
            w_cli.close()  # o banco fechou (Terminate): o `close()` do asyncpg espera isto

        try:
            await asyncio.gather(cliente_para_banco(), banco_para_cliente(), return_exceptions=True)
        finally:
            self._abertas.discard(w_cli)
            w_cli.transport.abort()
            w_srv.transport.abort()


@asynccontextmanager
async def _pool_pelo_proxy(pg_dsn: str, max_size: int) -> AsyncIterator[_ProxyQueDerruba]:
    assert connection._pool is None, "pool global vazou do teste anterior"
    url = urlsplit(pg_dsn)
    async with _ProxyQueDerruba(url.hostname or "127.0.0.1", url.port or 5432) as proxy:
        credenciais = url.netloc.rsplit("@", 1)[0]
        pelo_proxy = urlunsplit(url._replace(netloc=f"{credenciais}@127.0.0.1:{proxy.porta}"))
        await connection.init_pool(pelo_proxy, min_size=max_size, max_size=max_size)
        try:
            yield proxy
        finally:
            await connection.close_pool()


async def _aquecer(n: int) -> None:
    """Deixa `n` conexões vivas e ociosas no pool — o estado em que o F76 acontecia."""
    pool = connection.get_pool()
    retiradas = [pool.acquire() for _ in range(n)]
    conns = [await r.__aenter__() for r in retiradas]
    for c in conns:
        assert await c.fetchval("SELECT 1") == 1
    for r in reversed(retiradas):
        await r.__aexit__(None, None, None)


@pytest.mark.integration
async def test_pool_cru_entrega_a_falha_ao_chamador(pg_dsn: str) -> None:
    """Controle: sem o `PoolValidado`, a conexão derrubada vira erro para quem pediu."""
    async with _pool_pelo_proxy(pg_dsn, max_size=1) as proxy:
        await _aquecer(1)
        assert proxy.derrubar_as_ociosas() == 1
        cru = connection._pool
        assert cru is not None
        with pytest.raises((asyncpg.PostgresConnectionError, ConnectionError)):
            async with cru.acquire() as conn:
                await conn.fetchval("SELECT 1")


@pytest.mark.integration
@pytest.mark.parametrize("mortas", [1, 2])
async def test_pool_validado_reconecta_e_o_corpo_roda_uma_vez(pg_dsn: str, mortas: int) -> None:
    async with _pool_pelo_proxy(pg_dsn, max_size=mortas) as proxy:
        await _aquecer(mortas)
        assert proxy.derrubar_as_ociosas() == mortas
        antes = proxy.aceitas
        corpo = 0
        async with connection.get_pool().acquire() as conn:
            corpo += 1
            assert await conn.fetchval("SELECT 1") == 1
        assert corpo == 1
        # Uma reconexão só, mesmo com duas mortas: a fila é LIFO, e a 2ª retirada pega o
        # holder que falhou, agora vazio. Contado no proxy, não no log — o log depende da
        # configuração do structlog que outros testes da suíte deixam para trás.
        assert proxy.aceitas - antes == 1
