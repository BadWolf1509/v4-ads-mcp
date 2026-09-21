"""Ponte pra chamadas SINCRONAS de SDK saírem do event loop (F86).

Mora fora de `google_ads/` por origem histórica: nasceu cobrindo os DOIS
provedores. Hoje só o lado Google passa por aqui — o Meta saiu do escopo no
F190, quando `run_meta_graph_get` trocou o SDK `facebook_business` (síncrono,
`requests` por baixo) por `httpx.AsyncClient`. Aquele caminho virou `await` de
verdade e parou de competir por este pool de threads; o ganho é real e vale
registrar, porque era uma sequência de round-trips bloqueantes por causa da
paginação, não um só.

O que sobra:

- `google-ads` é um cliente gRPC **bloqueante**: `search`, `search_stream`,
  `mutate`, `upload_click_conversions` e os métodos de offline user data job
  param a thread até a resposta chegar.

Chamados direto de dentro de `async def`, param o event loop inteiro — e com
`--concurrency=80` isso serializa todos os requests da instância.

O caso mais afiado é o `/health?deep=1`: o `asyncio.timeout(5)` que a F77
introduziu **nem começa a contar**, porque o timer só dispara quando o loop volta
a girar. Era um caminho pra 503 no uptime check sem nenhum problema de banco,
indistinguível — pela evidência — do stale connection que a F77 perseguia.

Escopo: TODO caminho que atende request e chama SDK síncrono — os 5 executores
Google e `validate_gaql`, que constrói o client direto e não passa por executor
nenhum. O executor Meta saiu desta lista no F190 (é `httpx` async agora, não
tem o que offloadar). `accounts.py` continua síncrono de propósito: é consumido
apenas pelo Cloud Run Job de resync, que não serve tráfego.

O guard `test_chamada_bloqueante_sai_do_event_loop` mantém essa lista honesta —
quando o F86 foi fechado sem guard, três desses sites ficaram para trás.

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
