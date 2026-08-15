"""Bookkeeping (audit + reconciliacao de quota) que nao pode derrubar a operacao.

F83: excecao levantada dentro de um `finally` DESCARTA o `return` pendente do
`try` — semantica do Python, nao detalhe de implementacao. Os executores fazem
`pool.acquire()` cru no `finally`, entao uma conexao asyncpg stale (modo de
falha F76, 6 ocorrencias reais em producao) transformava uma mutacao JA APLICADA
no provider em erro pro gestor. Consequencia tripla: erro numa operacao que
funcionou, cliente LLM re-tentando operacao nao-idempotente (`add_keywords`,
`create_campaign`, `update_campaign_budget`), e nenhuma linha de audit — o
invariante "audit SEMPRE em mutates" quebrando justamente onde mais importa.

O bookkeeping OBSERVA a operacao; nao pode decidir o resultado dela. Aqui a
falha vira log ERROR — alertavel, porque `add_cloud_logging_severity` mapeia
`level`->`severity` no pipeline JSON — e o fluxo original segue intacto.

Deliberadamente SEM retry: re-executar um INSERT que pode ter commitado
duplicaria a linha de audit (CLAUDE.md: "mutacao NAO leva retry cego"). O ganho
aqui e trocar "erro opaco + audit perdido em silencio" por "resultado correto +
falha registrada", nao garantir a escrita.

`asyncio.CancelledError` herda de BaseException, entao cancelamento continua
propagando normalmente.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog

log = structlog.get_logger(__name__)


@asynccontextmanager
async def best_effort(event: str, **context: Any) -> AsyncIterator[None]:
    """Roda bookkeeping engolindo falha, com rastro alertavel (F83).

    Uso — sempre em volta do I/O de bookkeeping, nunca em volta da operacao::

        async with best_effort("mutation_audit_write_failed", operation=op):
            async with pool.acquire() as conn:
                await audit_log.record(conn, ...)
    """
    try:
        yield
    except Exception:
        log.exception(event, **context)
