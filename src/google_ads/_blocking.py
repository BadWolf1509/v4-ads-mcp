"""Ponte pra chamadas SINCRONAS do SDK Google saírem do event loop (F86).

O `google-ads` é um cliente gRPC **bloqueante**: `search_stream`, `mutate`,
`upload_click_conversions` e os métodos de offline user data job param a thread
até a resposta chegar. Chamados direto de dentro de `async def`, param o event
loop inteiro — e com `--concurrency=80` isso serializa todos os requests da
instância.

O caso mais afiado é o `/health?deep=1`: o `asyncio.timeout(5)` que a F77
introduziu **nem começa a contar**, porque o timer só dispara quando o loop volta
a girar. Era um caminho pra 503 no uptime check sem nenhum problema de banco,
indistinguível — pela evidência — do stale connection que a F77 perseguia.

Escopo: só os executores que atendem request. `accounts.py` continua síncrono de
propósito — é consumido apenas pelo Cloud Run Job de resync, que não serve
tráfego, então ali bloquear não tira nada de ninguém.

Nota sobre streaming: não basta tirar a CHAMADA do loop. `search_stream` devolve
um iterador cujo consumo é que faz a I/O — o `for batch in stream` precisa
acontecer dentro da mesma função offloaded, senão o bloqueio só muda de lugar.
"""

from __future__ import annotations

from collections.abc import Callable

import anyio.to_thread


async def run_blocking[T](fn: Callable[[], T]) -> T:
    """Roda `fn` numa worker thread, devolvendo o loop pros outros requests.

    Recebe um callable SEM argumentos de propósito: quem chama fecha o que
    precisa num closure, o que deixa explícito qual trecho — chamada **e**
    consumo do resultado — está saindo do loop.
    """
    return await anyio.to_thread.run_sync(fn)
