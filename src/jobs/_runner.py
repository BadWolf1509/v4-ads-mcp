"""Esqueleto comum dos Cloud Run Jobs de reconciliação.

Os dois jobs (`account_resync`, `meta_resync`) repetiam o mesmo invólucro: abrir
o pool, rodar o corpo, auditar crash inesperado (F93) e re-levantar, e fechar o
pool no `finally`. O invólucro vive aqui uma vez; o corpo de cada job decide o
exit code.

O que fica FORA daqui, de propósito: `get_settings()` + `configure_logging()`.
Os dois rodam antes do `init_pool` em cada `run()`, porque o corpo precisa das
mesmas settings e os testes dos jobs substituem esses nomes no namespace do
próprio job — `structlog.configure` é estado global do processo pytest
(ver test_job_partial_failure_audit.py).
"""

from collections.abc import Awaitable, Callable
from typing import Literal

from src.db import connection
from src.jobs._audit import record_job_crash

RegistrarCrash = Callable[..., Awaitable[None]]


async def executar_job(
    *,
    operation: str,
    platform: Literal["google", "meta"],
    database_url: str,
    corpo: Callable[[], Awaitable[int]],
    registrar_crash: RegistrarCrash = record_job_crash,
) -> int:
    """Roda `corpo` entre `init_pool` e `close_pool`; devolve o exit code dele.

    Exceção que escapa do corpo é crash inesperado (F93): grava `status=error`
    no audit com `operation`/`platform` e RE-LEVANTA — o Cloud Run vê a
    execução falhar, e o audit observa o crash sem substituí-lo
    (`record_job_crash` já embrulha o próprio I/O em `best_effort`, F83).

    `registrar_crash` existe para o job passar o nome resolvido no PRÓPRIO
    namespace: é lá que os testes do job o substituem.
    """
    await connection.init_pool(database_url)
    try:
        return await corpo()
    except Exception as e:
        await registrar_crash(operation=operation, platform=platform, exc=e)
        raise
    finally:
        await connection.close_pool()
